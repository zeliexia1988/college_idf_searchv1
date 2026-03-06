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
        geolocator = Nominatim(user_agent="france_college_v11")
        loc = geolocator.geocode(address + ", France", timeout=10)
        return (loc.latitude, loc.longitude) if loc else (48.8566, 2.3522)
    except: return (48.8566, 2.3522)

# --- 3. 数据处理核心逻辑 ---
@st.cache_data
def load_and_merge_data():
    file_main = "fr-en-college-idf-language.xlsx"
    file_sec = "fr-en-sections-internationales.xlsx"
    
    if not os.path.exists(file_main):
        st.error(f"找不到主文件: {file_main}")
        return None

    try:
        # A. 加载主表 (语言与基础信息)
        df_raw = pd.read_excel(file_main, engine='openpyxl')
        df_raw.columns = [str(c).strip() for c in df_raw.columns]
        
        # 自动识别列名逻辑
        def find_c(keys, d): 
            for k in keys:
                for c in d.columns:
                    if k.lower() in c.lower(): return c
            return None

        c_uai = find_c(['uai'], df_raw)
        c_name = find_c(['libellé'], df_raw)
        c_ips = find_c(['ips'], df_raw)
        c_ens = find_c(['enseignement'], df_raw)
        c_lang = find_c(['langue'], df_raw)
        c_sect = find_c(['secteur'], df_raw)

        # 聚合主表语种数据
        base = df_raw[[c_uai, c_name, c_sect, c_ips, 'Latitude', 'Longitude', 'Adresse', 'Commune']].drop_duplicates(subset=[c_uai])
        lv1 = df_raw[df_raw[c_ens].str.contains('LV1', na=False)].groupby(c_uai)[c_lang].apply(lambda x: list(set(x.astype(str).str.upper()))).reset_index()
        lv2 = df_raw[df_raw[c_ens].str.contains('LV2', na=False)].groupby(c_uai)[c_lang].apply(lambda x: list(set(x.astype(str).str.upper()))).reset_index()
        lca = df_raw[df_raw[c_ens].str.contains('LCA', na=False)].groupby(c_uai)[c_lang].apply(lambda x: list(set(x.astype(str).str.upper()))).reset_index()

        df = base.merge(lv1, on=c_uai, how='left').rename(columns={c_lang: 'lv1'})
        df = df.merge(lv2, on=c_uai, how='left').rename(columns={c_lang: 'lv2'})
        df = df.merge(lca, on=c_uai, how='left').rename(columns={c_lang: 'lca'})

        # B. 关联国际部文件
        if os.path.exists(file_sec):
            df_sec = pd.read_excel(file_sec, engine='openpyxl')
            df_sec.columns = [str(c).strip() for c in df_sec.columns]
            
            s_uai = find_c(['uai'], df_sec)
            s_type = find_c(['section'], df_sec) # 匹配 "Section International"
            
            # 将同一学校的多个国际部语种合并显示
            sec_agg = df_sec.groupby(s_uai)[s_type].apply(lambda x: ", ".join(set(x.astype(str)))).reset_index()
            df = df.merge(sec_agg, left_on=c_uai, right_on=s_uai, how='left')
            df['Section_Int'] = df[s_type].fillna("无 (Non)")
        else:
            df['Section_Int'] = "未找到数据文件"

        # C. 数据清洗
        df['final_ips'] = pd.to_numeric(df[c_ips].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)
        df['marker_color'] = df[c_sect].apply(lambda x: [0, 180, 0, 160] if 'PU' in str(x).upper() else [230, 0, 0, 160])
        
        # 菜单准备
        menus = {
            'lv1': sorted(list(set([l for sub in df['lv1'].dropna() for l in sub]))),
            'sec': sorted(df['Section_Int'].unique().tolist())
        }
        
        df.attrs.update({'config': {'name': c_name, 'sect': c_sect, 'uai': c_uai}, 'menus': menus})
        return df.dropna(subset=['Latitude', 'Longitude'])
    except Exception as e:
        st.error(f"❌ 关联数据失败: {e}")
        return None

# --- 4. 界面与交互 ---
df = load_and_merge_data()

if df is not None:
    with st.sidebar:
        st.header("📍 位置与半径")
        u_addr = st.text_input("中心地址", "Paris")
        h_coords = get_coords(u_addr)
        radius = st.slider("半径 (km)", 1, 50, 10)
        
        st.header("🎯 核心筛选")
        m = df.attrs['menus']
        # 1. 语言筛选
        sel_lv1 = st.selectbox("第一外语 (LV1)", m['lv1'], index=m['lv1'].index("ANGLAIS") if "ANGLAIS" in m['lv1'] else 0)
        # 2. 国际部筛选 (新加入)
        sel_sec = st.selectbox("国际部类型 (Section International)", ["全部"] + m['sec'])

        st.header("📊 IPS 评分")
        ips_range = st.slider("IPS 范围", 80.0, 160.0, (100.0, 150.0))

    # --- 筛选执行 ---
    df['dist'] = df.apply(lambda r: geodesic(h_coords, (r['Latitude'], r['Longitude'])).km, axis=1)
    
    mask = (df['dist'] <= radius) & (df['final_ips'].between(ips_range[0], ips_range[1]))
    mask &= df['lv1'].apply(lambda x: sel_lv1 in x if isinstance(x, list) else False)
    
    if sel_sec != "全部":
        mask &= (df['Section_Int'] == sel_sec)

    res = df[mask].sort_values("dist")

    # --- 5. 结果排版 ---
    st.title("🏫 法国中学智能选择系统 v2.0")
    st.markdown(f"找到满足条件的学校: **{len(res)}** 所")

    # 地图
    st.pydeck_chart(pdk.Deck(
        map_style=None,
        initial_view_state=pdk.ViewState(latitude=h_coords[0], longitude=h_coords[1], zoom=11),
        layers=[
            pdk.Layer("ScatterplotLayer", res, get_position=["Longitude", "Latitude"], get_color="marker_color", get_radius=200, pickable=True),
            pdk.Layer("ScatterplotLayer", pd.DataFrame([{"ln": h_coords[1], "lt": h_coords[0]}]), get_position=["ln", "lt"], get_color=[0, 100, 255], get_radius=400)
        ],
        tooltip={"text": "{Libellé}\n国际部: {Section_Int}\n地址: {Adresse}"}
    ))

    # 表格
    st.markdown("---")
    st.subheader("📋 详细信息清单")
    res['LV1_List'] = res['lv1'].apply(lambda x: ", ".join(x) if isinstance(x, list) else "")
    disp_cols = ['Libellé', 'Secteur', 'final_ips', 'dist', 'LV1_List', 'Section_Int', 'Adresse']
    st.dataframe(res[disp_cols].rename(columns={'final_ips': 'IPS', 'dist': '距离(km)', 'Section_Int': '国际部'}), use_container_width=True, hide_index=True)

    if not res.empty:
        st.download_button("📥 导出结果", res.to_csv(index=False).encode('utf-8-sig'), "college_results.csv")


