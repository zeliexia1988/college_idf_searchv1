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
        geolocator = Nominatim(user_agent="france_college_stable_v1")
        loc = geolocator.geocode(address + ", France", timeout=10)
        return (loc.latitude, loc.longitude) if loc else (48.8566, 2.3522)
    except: return (48.8566, 2.3522)

# --- 3. 核心数据加载 (支持双表+多语种) ---
@st.cache_data
def load_all_data():
    f_main = "fr-en-college-idf-language.xlsx"
    f_sec = "fr-en-sections-internationales.xlsx"
    
    if not os.path.exists(f_main):
        st.error(f"❌ 缺少主文件: {f_main}")
        return None

    try:
        df_raw = pd.read_excel(f_main, engine='openpyxl')
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

        # 基础数据
        base = df_raw[[c_uai, c_name, c_sect, c_ips, 'Latitude', 'Longitude', c_addr, c_comm]].drop_duplicates(subset=[c_uai])
        
        # 分类提取语言逻辑
        def get_lang(key):
            sub = df_raw[df_raw[c_ens].astype(str).str.contains(key, case=False, na=False)]
            return sub.groupby(c_uai)[c_lang].apply(lambda x: list(set(x.astype(str).str.upper()))).reset_index()

        df = base.merge(get_lang('LV1'), on=c_uai, how='left').rename(columns={c_lang: 'lv1_list'})
        df = df.merge(get_lang('LV2'), on=c_uai, how='left').rename(columns={c_lang: 'lv2_list'})
        df = df.merge(get_lang('LCA'), on=c_uai, how='left').rename(columns={c_lang: 'lca_list'})

        # 关联国际部
        if os.path.exists(f_sec):
            df_sec = pd.read_excel(f_sec, engine='openpyxl')
            df_sec.columns = [str(c).strip() for c in df_sec.columns]
            s_uai, s_type = find_c(['uai'], df_sec), find_c(['section'], df_sec)
            sec_menu = sorted(df_sec[s_type].unique().tolist())
            sec_agg = df_sec.groupby(s_uai)[s_type].apply(lambda x: " / ".join(set(x.astype(str)))).reset_index()
            df = df.merge(sec_agg, left_on=c_uai, right_on=s_uai, how='left')
            df['Section_Int'] = df[s_type].fillna("无 (Non)")
        else:
            sec_menu, df['Section_Int'] = [], "数据缺失"

        df['final_ips'] = pd.to_numeric(df[c_ips].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)
        df['marker_color'] = df[c_sect].apply(lambda x: [0, 180, 0, 160] if 'PU' in str(x).upper() else [230, 0, 0, 160])
        for col in ['lv1_list', 'lv2_list', 'lca_list']:
            df[col] = df[col].apply(lambda x: x if isinstance(x, list) else [])

        df.attrs['config'] = {'name': c_name, 'sect': c_sect, 'addr': c_addr, 'comm': c_comm}
        df.attrs['sec_menu'] = sec_menu
        return df.dropna(subset=['Latitude', 'Longitude'])
    except Exception as e:
        st.error(f"❌ 数据加载失败: {e}")
        return None

# --- 4. 界面展示 ---
df = load_all_data()

if df is not None:
    c = df.attrs['config']
    with st.sidebar:
        st.header("📍 1. 搜索位置")
        u_addr = st.text_input("中心地址", "Paris")
        h_coords = get_coords(u_addr)
        radius = st.slider("半径 (km)", 1, 50, 10)
        
        st.header("🎯 2. 精确筛选")
        # --- LV1, LV2, LCA 回归 ---
        all_lv1 = sorted(list(set([l for sub in df['lv1_list'] for l in sub])))
        sel_lv1 = st.selectbox("语言一 (LV1)", all_lv1, index=all_lv1.index("ANGLAIS") if "ANGLAIS" in all_lv1 else 0)
        
        all_lv2 = sorted(list(set([l for sub in df['lv2_list'] for l in sub])))
        sel_lv2 = st.selectbox("语言二 (LV2)", ["全部"] + all_lv2)
        
        all_lca = sorted(list(set([l for sub in df['lca_list'] for l in sub])))
        sel_lca = st.selectbox("语言三 (LCA)", ["全部"] + all_lca)

        st.markdown("---")
        # 国际部单独选项
        sel_sec = st.selectbox("国际部类型", ["全部", "仅看有国际部的学校"] + df.attrs['sec_menu'])
        
        ips_range = st.slider("IPS 范围", 80.0, 160.0, (100.0, 150.0))

    # --- 筛选逻辑 ---
    df['dist'] = df.apply(lambda r: geodesic(h_coords, (r['Latitude'], r['Longitude'])).km, axis=1)
    mask = (df['dist'] <= radius) & (df['final_ips'].between(ips_range[0], ips_range[1]))
    mask &= df['lv1_list'].apply(lambda x: sel_lv1 in x)
    if sel_lv2 != "全部": mask &= df['lv2_list'].apply(lambda x: sel_lv2 in x)
    if sel_lca != "全部": mask &= df['lca_list'].apply(lambda x: sel_lca in x)
    if sel_sec == "仅看有国际部的学校": mask &= (df['Section_Int'] != "无 (Non)")
    elif sel_sec != "全部": mask &= df['Section_Int'].str.contains(sel_sec, na=False)
    
    res = df[mask].sort_values("dist").copy()

    # --- 5. 地图定位与展示 ---
    st.title("🏫 法国中学智能选择系统")
    
    # 联动跳转：使用 Selectbox 避免 Dataframe 选择报错
    target_school = st.selectbox("📍 在地图上快速定位学校：", ["-- 请选择学校 --"] + res[c['name']].tolist())
    
    view_lat, view_lon, zoom = h_coords[0], h_coords[1], 11
    if target_school != "-- 请选择学校 --":
        s_data = res[res[c['name']] == target_school].iloc[0]
        view_lat, view_lon, zoom = s_data['Latitude'], s_data['Longitude'], 15

    st.pydeck_chart(pdk.Deck(
        map_style=None,
        initial_view_state=pdk.ViewState(latitude=view_lat, longitude=view_lon, zoom=zoom),
        layers=[
            pdk.Layer("ScatterplotLayer", res, get_position=["Longitude", "Latitude"], get_color="marker_color", get_radius=200, pickable=True),
            pdk.Layer("ScatterplotLayer", pd.DataFrame([{"ln": h_coords[1], "lt": h_coords[0]}]), get_position=["ln", "lt"], get_color=[0, 100, 255], get_radius=400)
        ],
        tooltip={"html": f"<b>{{{c['name']}}}</b><br/>地址: {{{c['addr']}}}<br/>城市: {{{c['comm']}}}<br/>国际部: {{Section_Int}}"}
    ))

    # --- 6. 结果清单 ---
    st.markdown("---")
    res['LV1'] = res['lv1_list'].apply(lambda x: ", ".join(x))
    res['LV2'] = res['lv2_list'].apply(lambda x: ", ".join(x))
    res['LCA'] = res['lca_list'].apply(lambda x: ", ".join(x))
    
    # 确保列名在显示前已重命名，防止 KeyError
    disp_res = res.rename(columns={c['name']: '学校', 'final_ips': 'IPS', 'dist': '距离(km)', 'Section_Int': '国际部', c['addr']: '地址'})
    show_cols = ['学校', 'IPS', '距离(km)', 'LV1', 'LV2', 'LCA', '国际部', '地址']
    
    st.dataframe(disp_res[show_cols], use_container_width=True, hide_index=True)
