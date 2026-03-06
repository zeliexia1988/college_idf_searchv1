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
        geolocator = Nominatim(user_agent="france_college_v2_final")
        loc = geolocator.geocode(address + ", France", timeout=10)
        return (loc.latitude, loc.longitude) if loc else (48.8566, 2.3522)
    except: return (48.8566, 2.3522)

# --- 3. 数据处理核心逻辑 ---
@st.cache_data
def load_and_merge_data():
    file_main = "fr-en-college-idf-language.xlsx"
    file_sec = "fr-en-sections-internationales.xlsx"
    
    if not os.path.exists(file_main):
        st.error(f"❌ 找不到主文件: {file_main}，请确保已上传。")
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

        # 聚合基础信息与语种
        base = df_raw[[c_uai, c_name, c_sect, c_ips, 'Latitude', 'Longitude', 'Adresse', 'Commune']].drop_duplicates(subset=[c_uai])
        
        # 语种分类提取
        def get_lang_list(key):
            subset = df_raw[df_raw[c_ens].astype(str).str.contains(key, na=False)]
            return subset.groupby(c_uai)[c_lang].apply(lambda x: list(set(x.astype(str).str.upper()))).reset_index()

        df = base.merge(get_lang_list('LV1'), on=c_uai, how='left').rename(columns={c_lang: 'lv1'})
        df = df.merge(get_lang_list('LV2'), on=c_uai, how='left').rename(columns={c_lang: 'lv2'})
        df = df.merge(get_lang_list('LCA'), on=c_uai, how='left').rename(columns={c_lang: 'lca'})

        # B. 关联国际部文件 (Section International)
        if os.path.exists(file_sec):
            df_sec = pd.read_excel(file_sec, engine='openpyxl')
            df_sec.columns = [str(c).strip() for c in df_sec.columns]
            
            s_uai = find_c(['uai'], df_sec)
            s_type = find_c(['section'], df_sec) # 匹配 "Section International"
            
            # 合并同一学校的多个国际部条目
            sec_agg = df_sec.groupby(s_uai)[s_type].apply(lambda x: " / ".join(set(x.astype(str)))).reset_index()
            df = df.merge(sec_agg, left_on=c_uai, right_on=s_uai, how='left')
            df['Section_Int'] = df[s_type].fillna("无 (Non)")
        else:
            df['Section_Int'] = "数据文件缺失"

        # C. 清洗坐标与评分
        df['final_ips'] = pd.to_numeric(df[c_ips].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)
        df['marker_color'] = df[c_sect].apply(lambda x: [0, 180, 0, 160] if 'PU' in str(x).upper() else [230, 0, 0, 160])
        
        # 记录配置信息
        df.attrs['config'] = {'name': c_name, 'sect': c_sect, 'uai': c_uai}
        return df.dropna(subset=['Latitude', 'Longitude'])
    except Exception as e:
        st.error(f"❌ 数据合并失败: {e}")
        return None

# --- 4. 侧边栏与交互 ---
df = load_and_merge_data()

if df is not None:
    with st.sidebar:
        st.header("📍 搜索中心")
        u_addr = st.text_input("输入地址 (Paris, Versailles...)", "Paris")
        h_coords = get_coords(u_addr)
        radius = st.slider("半径 (km)", 1, 50, 10)
        
        st.header("🎯 课程要求")
        # 提取 LV1 菜单
        all_lv1 = sorted(list(set([l for sub in df['lv1'].dropna() for l in sub])))
        sel_lv1 = st.selectbox("第一外语 (LV1)", all_lv1, index=all_lv1.index("ANGLAIS") if "ANGLAIS" in all_lv1 else 0)
        
        # 提取国际部菜单
        all_sec = sorted(df['Section_Int'].unique().tolist())
        sel_sec = st.selectbox("国际部筛选 (Section International)", ["全部"] + all_sec)

        st.header("📊 IPS 指标")
        ips_range = st.slider("评分范围", 80.0, 160.0, (100.0, 150.0))

    # --- 执行筛选 ---
    df['dist'] = df.apply(lambda r: geodesic(h_coords, (r['Latitude'], r['Longitude'])).km, axis=1)
    
    mask = (df['dist'] <= radius) & (df['final_ips'].between(ips_range[0], ips_range[1]))
    mask &= df['lv1'].apply(lambda x: sel_lv1 in x if isinstance(x, list) else False)
    
    if sel_sec != "全部":
        mask &= (df['Section_Int'] == sel_sec)

    res = df[mask].sort_values("dist").copy()

    # --- 5. 渲染显示 ---
    st.title("🏫 法国中学智能选择系统")
    st.markdown(f"当前筛选条件下共有 **{len(res)}** 所学校")

    # A. 地图
    st.pydeck_chart(pdk.Deck(
        map_style=None, # 使用默认白图底色以防网络问题
        initial_view_state=pdk.ViewState(latitude=h_coords[0], longitude=h_coords[1], zoom=11),
        layers=[
            pdk.Layer("ScatterplotLayer", res, get_position=["Longitude", "Latitude"], get_color="marker_color", get_radius=200, pickable=True),
            pdk.Layer("ScatterplotLayer", pd.DataFrame([{"ln": h_coords[1], "lt": h_coords[0]}]), get_position=["ln", "lt"], get_color=[0, 100, 255], get_radius=400)
        ],
        tooltip={"text": "{Libellé}\n国际部: {Section_Int}\n地址: {Adresse}"}
    ))

    # B. 结果列表
    st.markdown("---")
    st.subheader("📋 学校详细资料")
    
    # 转换列以便显示
    res['LV1_List'] = res['lv1'].apply(lambda x: ", ".join(x) if isinstance(x, list) else "")
    
    # 安全定义显示列
    c = df.attrs['config']
    final_cols = [c['name'], c['sect'], 'final_ips', 'dist', 'LV1_List', 'Section_Int', 'Adresse']
    
    # 重命名映射
    rename_dict = {c['name']: '学校名称', c['sect']: '性质', 'final_ips': 'IPS评分', 'dist': '距离(km)', 'Section_Int': '国际部/Section'}
    
    st.dataframe(
        res[final_cols].rename(columns=rename_dict),
        use_container_width=True, 
        hide_index=True, 
        height=400
    )

    if not res.empty:
        csv = res.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 导出结果为 CSV", csv, "middle_school_results.csv", "text/csv")



