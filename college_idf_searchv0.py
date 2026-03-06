import streamlit as st
import pandas as pd
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
import pydeck as pdk 
import os

# --- 1. 页面配置 ---
st.set_page_config(page_title="法国中学智能选择系统", layout="wide")

# --- 2. 地理编码 ---
@st.cache_data
def get_coords(address):
    try:
        geolocator = Nominatim(user_agent="france_college_v15_interaction")
        loc = geolocator.geocode(address + ", France", timeout=10)
        return (loc.latitude, loc.longitude) if loc else (48.8566, 2.3522)
    except: return (48.8566, 2.3522)

# --- 3. 数据处理逻辑 ---
@st.cache_data
def load_all_data():
    file_main = "fr-en-college-idf-language.xlsx"
    file_sec = "fr-en-sections-internationales.xlsx"
    
    if not os.path.exists(file_main):
        st.error(f"❌ 找不到主文件: {file_main}")
        return None

    try:
        df_raw = pd.read_excel(file_main, engine='openpyxl')
        df_raw.columns = [str(c).strip() for c in df_raw.columns]
        
        def find_c(keys, d): 
            for c in d.columns:
                if any(k.lower() in c.lower() for k in keys): return c
            return None

        c_uai = find_c(['uai'], df_raw)
        c_name = find_c(['libellé', 'nom'], df_raw)
        c_ips = find_c(['ips'], df_raw)
        c_ens = find_c(['enseignement'], df_raw)
        c_lang = find_c(['langue'], df_raw)
        c_sect = find_c(['secteur'], df_raw)
        c_comm = find_c(['commune'], df_raw)
        c_addr = find_c(['adresse'], df_raw)

        base = df_raw[[c_uai, c_name, c_sect, c_ips, 'Latitude', 'Longitude', c_addr, c_comm]].drop_duplicates(subset=[c_uai])
        
        def get_lang_subset(key):
            subset = df_raw[df_raw[c_ens].astype(str).str.contains(key, case=False, na=False)]
            return subset.groupby(c_uai)[c_lang].apply(lambda x: list(set(x.astype(str).str.upper()))).reset_index()

        df = base.merge(get_lang_subset('LV1'), on=c_uai, how='left').rename(columns={c_lang: 'lv1_list'})
        df = df.merge(get_lang_subset('LV2'), on=c_uai, how='left').rename(columns={c_lang: 'lv2_list'})
        df = df.merge(get_lang_subset('LCA'), on=c_uai, how='left').rename(columns={c_lang: 'lca_list'})

        if os.path.exists(file_sec):
            df_sec = pd.read_excel(file_sec, engine='openpyxl')
            df_sec.columns = [str(c).strip() for c in df_sec.columns]
            s_uai = find_c(['uai'], df_sec)
            s_type = find_c(['section'], df_sec)
            sec_items = sorted(df_sec[s_type].unique().tolist())
            sec_agg = df_sec.groupby(s_uai)[s_type].apply(lambda x: " / ".join(set(x.astype(str)))).reset_index()
            df = df.merge(sec_agg, left_on=c_uai, right_on=s_uai, how='left')
            df['Section_Int'] = df[s_type].fillna("无 (Non)")
        else:
            sec_items = []
            df['Section_Int'] = "数据文件缺失"

        df['final_ips'] = pd.to_numeric(df[c_ips].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)
        df['marker_color'] = df[c_sect].apply(lambda x: [0, 180, 0, 160] if 'PU' in str(x).upper() else [230, 0, 0, 160])
        for col in ['lv1_list', 'lv2_list', 'lca_list']:
            df[col] = df[col].apply(lambda x: x if isinstance(x, list) else [])

        df.attrs['config'] = {'name': c_name, 'sect': c_sect, 'uai': c_uai, 'addr': c_addr, 'comm': c_comm}
        df.attrs['sec_menu'] = sec_items
        return df.dropna(subset=['Latitude', 'Longitude'])
    except Exception as e:
        st.error(f"❌ 初始化失败: {e}")
        return None

# --- 4. 主逻辑 ---
df = load_all_data()

if df is not None:
    c_cfg = df.attrs['config']
    
    # 侧边栏
    with st.sidebar:
        st.header("📍 搜索设置")
        u_addr = st.text_input("中心地址", "Paris")
        h_coords = get_coords(u_addr)
        radius = st.slider("半径 (km)", 1, 50, 10)
        
        st.header("🎯 课程与国际部")
        lv1_opts = sorted(list(set([l for sub in df['lv1_list'] for l in sub])))
        sel_lv1 = st.selectbox("语言一 (LV1)", lv1_opts, index=lv1_opts.index("ANGLAIS") if "ANGLAIS" in lv1_opts else 0)
        
        sec_menu = df.attrs['sec_menu']
        sel_sec = st.selectbox("国际部", ["全部", "仅看有国际部的学校"] + sec_menu)
        
        ips_range = st.slider("IPS 范围", 80.0, 160.0, (100.0, 150.0))

    # 初始筛选
    df['dist'] = df.apply(lambda r: geodesic(h_coords, (r['Latitude'], r['Longitude'])).km, axis=1)
    mask = (df['dist'] <= radius) & (df['final_ips'].between(ips_range[0], ips_range[1]))
    mask &= df['lv1_list'].apply(lambda x: sel_lv1 in x)
    if sel_sec == "仅看有国际部的学校": mask &= (df['Section_Int'] != "无 (Non)")
    elif sel_sec != "全部": mask &= df['Section_Int'].str.contains(sel_sec, na=False)
    
    res = df[mask].sort_values("dist").reset_index(drop=True)

    # --- 核心改进：处理表格选择 ---
    st.title("🏫 法国中学智能选择系统")
    
    # 准备表格显示
    res['LV1'] = res['lv1_list'].apply(lambda x: ", ".join(x))
    res['LV2'] = res['lv2_list'].apply(lambda x: ", ".join(x))
    res['LCA'] = res['lca_list'].apply(lambda x: ", ".join(x))
    disp_cols = [c_cfg['name'], 'final_ips', 'dist', 'LV1', 'LV2', 'LCA', 'Section_Int', c_cfg['addr']]
    rename_map = {c_cfg['name']: '学校名称', 'final_ips': 'IPS', 'dist': '距离', 'Section_Int': '国际部'}

    # 渲染结果表格（开启选择功能）
    st.subheader(f"📋 结果清单 (点击行在地图定位)")
    event = st.dataframe(
        res[disp_cols].rename(columns=rename_map),
        use_container_width=True,
        hide_index=True,
        on_select="rerun",  # 关键：选中时触发重新运行
        selection_mode="single_row"
    )

    # 确定地图中心点
    view_lat, view_lon, zoom_level = h_coords[0], h_coords[1], 11
    
    # 如果选中了某一行
    selected_indices = event.get("selection", {}).get("rows", [])
    if selected_indices:
        selected_row = res.iloc[selected_indices[0]]
        view_lat = selected_row['Latitude']
        view_lon = selected_row['Longitude']
        zoom_level = 15 # 自动放大
        st.success(f"📍 已定位到：{selected_row[c_cfg['name']]}")

    # --- 5. 地图渲染 ---
    tooltip_config = {
        "html": f"<b>{{{c_cfg['name']}}}</b><br/>地址: {{{c_cfg['addr']}}}<br/>城市: {{{c_cfg['comm']}}}<br/>国际部: {{Section_Int}}",
        "style": {"backgroundColor": "steelblue", "color": "white"}
    }

    st.pydeck_chart(pdk.Deck(
        map_style=None,
        initial_view_state=pdk.ViewState(
            latitude=view_lat, 
            longitude=view_lon, 
            zoom=zoom_level, 
            pitch=0
        ),
        layers=[
            # 常规学校点
            pdk.Layer("ScatterplotLayer", res, get_position=["Longitude", "Latitude"], 
                      get_color="marker_color", get_radius=220, pickable=True),
            # 用户搜索中心点
            pdk.Layer("ScatterplotLayer", pd.DataFrame([{"ln": h_coords[1], "lt": h_coords[0]}]), 
                      get_position=["ln", "lt"], get_color=[0, 100, 255], get_radius=400),
            # 选中高亮圈
            pdk.Layer("ScatterplotLayer", 
                      res.iloc[selected_indices] if selected_indices else pd.DataFrame(),
                      get_position=["Longitude", "Latitude"], get_color=[255, 255, 0], 
                      get_radius=500, stroked=True, line_width_min_pixels=3)
        ],
        tooltip=tooltip_config
    ))

