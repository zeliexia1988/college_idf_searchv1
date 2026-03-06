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
        geolocator = Nominatim(user_agent="france_college_v14_split")
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

        # --- 国际部数据处理逻辑优化 ---
        if os.path.exists(file_sec):
            df_sec = pd.read_excel(file_sec, engine='openpyxl')
            df_sec.columns = [str(c).strip() for c in df_sec.columns]
            s_uai = find_c(['uai'], df_sec)
            s_type = find_c(['section'], df_sec)
            
            # 存储原始独立项供菜单使用
            raw_sec_items = sorted(df_sec[s_type].unique().tolist())
            
            # 合并展示项 (用 / 分隔)
            sec_agg = df_sec.groupby(s_uai)[s_type].apply(lambda x: " / ".join(set(x.astype(str)))).reset_index()
            df = df.merge(sec_agg, left_on=c_uai, right_on=s_uai, how='left')
            df['Section_Int'] = df[s_type].fillna("无 (Non)")
        else:
            raw_sec_items = []
            df['Section_Int'] = "数据文件缺失"

        df['final_ips'] = pd.to_numeric(df[c_ips].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)
        df['marker_color'] = df[c_sect].apply(lambda x: [0, 180, 0, 160] if 'PU' in str(x).upper() else [230, 0, 0, 160])
        for col in ['lv1_list', 'lv2_list', 'lca_list']:
            df[col] = df[col].apply(lambda x: x if isinstance(x, list) else [])

        df.attrs['config'] = {'name': c_name, 'sect': c_sect, 'uai': c_uai, 'addr': c_addr, 'comm': c_comm}
        df.attrs['sec_menu'] = raw_sec_items # 存入独立的国际部列表
        return df.dropna(subset=['Latitude', 'Longitude'])
    except Exception as e:
        st.error(f"❌ 初始化失败: {e}")
        return None

# --- 4. 界面与筛选 ---
df = load_all_data()

if df is not None:
    c_cfg = df.attrs['config']
    with st.sidebar:
        st.header("📍 位置控制")
        u_addr = st.text_input("中心地址", "Paris")
        h_coords = get_coords(u_addr)
        radius = st.slider("半径 (km)", 1, 50, 10)
        
        st.header("🎯 课程筛选")
        lv1_opts = sorted(list(set([l for sub in df['lv1_list'] for l in sub])))
        sel_lv1 = st.selectbox("语言一 (LV1)", lv1_opts, index=lv1_opts.index("ANGLAIS") if "ANGLAIS" in lv1_opts else 0)
        
        lv2_opts = sorted(list(set([l for sub in df['lv2_list'] for l in sub])))
        sel_lv2 = st.selectbox("语言二 (LV2)", ["全部"] + lv2_opts)
        
        lca_opts = sorted(list(set([l for sub in df['lca_list'] for l in sub])))
        sel_lca = st.selectbox("语言三 (LCA)", ["全部"] + lca_opts)

        # --- 国际部菜单：使用拆分后的列表 ---
        sec_menu_items = df.attrs['sec_menu']
        sel_sec = st.selectbox("国际部 (Section International)", ["全部", "仅看有国际部的学校"] + sec_menu_items)

        st.header("📊 IPS 评分")
        ips_range = st.slider("范围", 80.0, 160.0, (100.0, 150.0))

    # --- 执行筛选逻辑 ---
    df['dist'] = df.apply(lambda r: geodesic(h_coords, (r['Latitude'], r['Longitude'])).km, axis=1)
    mask = (df['dist'] <= radius) & (df['final_ips'].between(ips_range[0], ips_range[1]))
    mask &= df['lv1_list'].apply(lambda x: sel_lv1 in x)
    
    if sel_lv2 != "全部": mask &= df['lv2_list'].apply(lambda x: sel_lv2 in x)
    if sel_lca != "全部": mask &= df['lca_list'].apply(lambda x: sel_lca in x)
    
    # 国际部筛选逻辑优化
    if sel_sec == "仅看有国际部的学校":
        mask &= (df['Section_Int'] != "无 (Non)")
    elif sel_sec != "全部":
        # 使用 contains 确保合并项也能被搜到
        mask &= df['Section_Int'].str.contains(sel_sec, na=False, regex=False)
    
    res = df[mask].sort_values("dist").copy()

    # --- 5. 地图展示 ---
    st.title("🏫 法国中学智能选择系统")
    st.subheader(f"🗺️ 空间分布 (共 {len(res)} 所)")

    tooltip_config = {
        "html": f"""
            <b>学校名称:</b> {{{c_cfg['name']}}} <br/>
            <b>地址:</b> {{{c_cfg['addr']}}} <br/>
            <b>城市:</b> {{{c_cfg['comm']}}} <br/>
            <b>国际部:</b> {{Section_Int}} <br/>
            <b>IPS:</b> {{final_ips}}
        """,
        "style": {"backgroundColor": "steelblue", "color": "white", "fontSize": "14px"}
    }

    st.pydeck_chart(pdk.Deck(
        map_style=None,
        initial_view_state=pdk.ViewState(latitude=h_coords[0], longitude=h_coords[1], zoom=11),
        layers=[
            pdk.Layer("ScatterplotLayer", res, get_position=["Longitude", "Latitude"], 
                      get_color="marker_color", get_radius=220, pickable=True),
            pdk.Layer("ScatterplotLayer", pd.DataFrame([{"ln": h_coords[1], "lt": h_coords[0]}]), 
                      get_position=["ln", "lt"], get_color=[0, 100, 255], get_radius=400)
        ],
        tooltip=tooltip_config
    ))

    # --- 6. 表格展示 ---
    st.markdown("---")
    res['LV1'] = res['lv1_list'].apply(lambda x: ", ".join(x))
    res['LV2'] = res['lv2_list'].apply(lambda x: ", ".join(x))
    res['LCA'] = res['lca_list'].apply(lambda x: ", ".join(x))
    
    final_disp = [c_cfg['name'], 'final_ips', 'dist', 'LV1', 'LV2', 'LCA', 'Section_Int', c_cfg['addr']]
    st.dataframe(res[final_disp].rename(columns={c_cfg['name']: '学校', 'final_ips': 'IPS', 'dist': '距离(km)', 'Section_Int': '国际部/Section'}), 
                 use_container_width=True, hide_index=True)


