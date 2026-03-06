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
        geolocator = Nominatim(user_agent="france_college_v12_full")
        loc = geolocator.geocode(address + ", France", timeout=10)
        return (loc.latitude, loc.longitude) if loc else (48.8566, 2.3522)
    except: return (48.8566, 2.3522)

# --- 3. 数据处理核心逻辑 (多表联动+多语种分类) ---
@st.cache_data
def load_all_data():
    file_main = "fr-en-college-idf-language.xlsx"
    file_sec = "fr-en-sections-internationales.xlsx"
    
    if not os.path.exists(file_main):
        st.error(f"❌ 找不到主文件: {file_main}")
        return None

    try:
        # A. 加载主表
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

        # 提取基础信息
        base = df_raw[[c_uai, c_name, c_sect, c_ips, 'Latitude', 'Longitude', 'Adresse', 'Commune']].drop_duplicates(subset=[c_uai])
        
        # --- 核心回归：分类提取 LV1, LV2, LCA ---
        def get_lang_subset(key):
            subset = df_raw[df_raw[c_ens].astype(str).str.contains(key, case=False, na=False)]
            return subset.groupby(c_uai)[c_lang].apply(lambda x: list(set(x.astype(str).str.upper()))).reset_index()

        df = base.merge(get_lang_subset('LV1'), on=c_uai, how='left').rename(columns={c_lang: 'lv1_list'})
        df = df.merge(get_lang_subset('LV2'), on=c_uai, how='left').rename(columns={c_lang: 'lv2_list'})
        df = df.merge(get_lang_subset('LCA'), on=c_uai, how='left').rename(columns={c_lang: 'lca_list'})

        # B. 关联国际部文件
        if os.path.exists(file_sec):
            df_sec = pd.read_excel(file_sec, engine='openpyxl')
            df_sec.columns = [str(c).strip() for c in df_sec.columns]
            s_uai = find_c(['uai'], df_sec)
            s_type = find_c(['section'], df_sec)
            
            sec_agg = df_sec.groupby(s_uai)[s_type].apply(lambda x: " / ".join(set(x.astype(str)))).reset_index()
            df = df.merge(sec_agg, left_on=c_uai, right_on=s_uai, how='left')
            df['Section_Int'] = df[s_type].fillna("无 (Non)")
        else:
            df['Section_Int'] = "数据文件未上传"

        # C. 清洗与转换
        df['final_ips'] = pd.to_numeric(df[c_ips].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)
        df['marker_color'] = df[c_sect].apply(lambda x: [0, 180, 0, 160] if 'PU' in str(x).upper() else [230, 0, 0, 160])
        
        # 菜单准备 (将空值转为空列表防止后续报错)
        for col in ['lv1_list', 'lv2_list', 'lca_list']:
            df[col] = df[col].apply(lambda x: x if isinstance(x, list) else [])

        menus = {
            'lv1': sorted(list(set([l for sub in df['lv1_list'] for l in sub]))),
            'lv2': sorted(list(set([l for sub in df['lv2_list'] for l in sub]))),
            'lca': sorted(list(set([l for sub in df['lca_list'] for l in sub]))),
            'sec': sorted(df['Section_Int'].unique().tolist())
        }
        
        df.attrs['config'] = {'name': c_name, 'sect': c_sect, 'uai': c_uai}
        df.attrs['menus'] = menus
        return df.dropna(subset=['Latitude', 'Longitude'])
    except Exception as e:
        st.error(f"❌ 初始化失败: {e}")
        return None

# --- 4. 侧边栏 ---
df = load_all_data()

if df is not None:
    with st.sidebar:
        st.header("📍 位置与半径")
        u_addr = st.text_input("搜索中心", "Paris")
        h_coords = get_coords(u_addr)
        radius = st.slider("半径 (km)", 1, 50, 10)
        
        st.header("🎯 课程精准筛选")
        m = df.attrs['menus']
        # 语言一、二、三回归
        sel_lv1 = st.selectbox("语言一 (LV1 - 必选)", m['lv1'], index=m['lv1'].index("ANGLAIS") if "ANGLAIS" in m['lv1'] else 0)
        sel_lv2 = st.selectbox("语言二 (LV2 - 选填)", ["全部 (Tous)"] + m['lv2'])
        sel_lca = st.selectbox("语言三 (LCA - 选填)", ["全部 (Tous)"] + m['lca'])
        
        st.markdown("---")
        # 国际部筛选
        sel_sec = st.selectbox("国际部 (Section International)", ["全部"] + m['sec'])

        st.header("📊 IPS 指标")
        ips_range = st.slider("IPS 范围", 80.0, 160.0, (100.0, 150.0))

    # --- 执行筛选 ---
    df['dist'] = df.apply(lambda r: geodesic(h_coords, (r['Latitude'], r['Longitude'])).km, axis=1)
    
    # 基础筛选 (距离+IPS)
    mask = (df['dist'] <= radius) & (df['final_ips'].between(ips_range[0], ips_range[1]))
    
    # 语言一 (LV1)
    mask &= df['lv1_list'].apply(lambda x: sel_lv1 in x)
    
    # 语言二 (LV2)
    if sel_lv2 != "全部 (Tous)":
        mask &= df['lv2_list'].apply(lambda x: sel_lv2 in x)
        
    # 语言三 (LCA)
    if sel_lca != "全部 (Tous)":
        mask &= df['lca_list'].apply(lambda x: sel_lca in x)
        
    # 国际部
    if sel_sec != "全部":
        mask &= (df['Section_Int'] == sel_sec)

    res = df[mask].sort_values("dist").copy()

    # --- 5. 渲染页面 ---
    st.title("🏫 法国中学智能选择系统 (全功能版)")
    st.info(f"找到符合条件的学校：{len(res)} 所")

    # 地图
    st.pydeck_chart(pdk.Deck(
        map_style=None,
        initial_view_state=pdk.ViewState(latitude=h_coords[0], longitude=h_coords[1], zoom=11),
        layers=[
            pdk.Layer("ScatterplotLayer", res, get_position=["Longitude", "Latitude"], get_color="marker_color", get_radius=200, pickable=True),
            pdk.Layer("ScatterplotLayer", pd.DataFrame([{"ln": h_coords[1], "lt": h_coords[0]}]), get_position=["ln", "lt"], get_color=[0, 100, 255], get_radius=400)
        ],
        tooltip={"text": "{Libellé}\nLV1: {lv1_str}\nLV2: {lv2_str}\n国际部: {Section_Int}"}
    ))

    # 结果清单
    st.markdown("---")
    res['lv1_str'] = res['lv1_list'].apply(lambda x: ", ".join(x))
    res['lv2_str'] = res['lv2_list'].apply(lambda x: ", ".join(x))
    res['lca_str'] = res['lca_list'].apply(lambda x: ", ".join(x))
    
    c = df.attrs['config']
    disp = [c['name'], 'final_ips', 'dist', 'lv1_str', 'lv2_str', 'lca_str', 'Section_Int', 'Adresse']
    
    st.dataframe(
        res[disp].rename(columns={c['name']: '学校名称', 'final_ips': 'IPS', 'dist': '距离(km)', 'lv1_str': 'LV1', 'lv2_str': 'LV2', 'lca_str': 'LCA', 'Section_Int': '国际部'}),
        use_container_width=True, hide_index=True
    )




