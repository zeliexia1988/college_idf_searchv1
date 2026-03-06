import streamlit as st
import pandas as pd
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
import pydeck as pdk 
import os

# --- 1. 页面配置 ---
st.set_page_config(page_title="法国中学智能选择系统", layout="wide", initial_sidebar_state="expanded")

# --- 2. 地理编码函数 ---
@st.cache_data
def get_coords_from_address(address):
    try:
        # 增加 timeout 提高成功率
        geolocator = Nominatim(user_agent="france_college_locator_v9")
        location = geolocator.geocode(address + ", France", timeout=10) 
        if location: return (location.latitude, location.longitude)
        return None
    except Exception: return None

# --- 3. 核心数据解析逻辑 ---
@st.cache_data
def load_and_pivot_data():
    target_file = "fr-en-college-idf-language.xlsx"
    if not os.path.exists(target_file):
        files = [f for f in os.listdir('.') if f.endswith('.xlsx')]
        if files: target_file = files[0]
        else: return None

    try:
        # 读取数据并清洗空格
        df_raw = pd.read_excel(target_file, engine='openpyxl')
        df_raw.columns = [str(c).strip() for c in df_raw.columns]
        
        # 自动识别列名逻辑 (增强容错)
        def get_col(keys):
            for k in keys:
                for c in df_raw.columns:
                    if k.lower() in c.lower(): return c
            raise KeyError(f"未找到包含 {keys} 的列")

        c_ens = get_col(['enseignement'])
        c_lang = get_col(['langue'])
        c_name = get_col(['libellé', 'nom'])
        c_ips = get_col(['ips'])
        c_lat = get_col(['latitude'])
        c_lon = get_col(['longitude'])
        c_sect = get_col(['secteur'])
        c_comm = get_col(['commune'])
        c_addr = next((c for c in df_raw.columns if 'adresse' in c.lower()), c_comm)

        # 1. 提取学校基础信息
        base_df = df_raw[[c_name, c_comm, c_sect, c_ips, c_lat, c_lon, c_addr]].drop_duplicates(subset=[c_name])
        
        # 2. 透视语种信息
        def get_pivot(ens_key):
            subset = df_raw[df_raw[c_ens].astype(str).str.contains(ens_key, case=False, na=False)]
            return subset.groupby(c_name)[c_lang].apply(lambda x: list(set(x.astype(str).str.capitalize()))).reset_index()

        lv1 = get_pivot("LV1")
        lv2 = get_pivot("LV2")
        lca = get_pivot("LCA")

        # 3. 合并到主表
        df = base_df.merge(lv1, on=c_name, how='left').rename(columns={c_lang: 'lv1_list'})
        df = df.merge(lv2, on=c_name, how='left').rename(columns={c_lang: 'lv2_list'})
        df = df.merge(lca, on=c_name, how='left').rename(columns={c_lang: 'lca_list'})

        # 填充空列表避免筛选报错
        for col in ['lv1_list', 'lv2_list', 'lca_list']:
            df[col] = df[col].apply(lambda x: x if isinstance(x, list) else [])

        # 类型转换
        df['final_lat'] = pd.to_numeric(df[c_lat], errors='coerce')
        df['final_lon'] = pd.to_numeric(df[c_lon], errors='coerce')
        df['final_ips'] = pd.to_numeric(df[c_ips].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)
        
        # 提取下拉菜单列表
        menus = {
            'lv1': sorted(list(set([l for sub in df['lv1_list'] for l in sub]))),
            'lv2': sorted(list(set([l for sub in df['lv2_list'] for l in sub]))),
            'lca': sorted(list(set([l for sub in df['lca_list'] for l in sub])))
        }

        # 设置地图点颜色
        df['marker_color'] = df[c_sect].apply(lambda x: [0, 180, 0, 160] if 'public' in str(x).lower() else [230, 0, 0, 160])
        
        df.attrs.update({'config': {'name': c_name, 'comm': c_comm, 'sect': c_sect, 'addr': c_addr}, 'menus': menus})
        return df.dropna(subset=['final_lat', 'final_lon'])
    except Exception as e:
        st.error(f"❌ 数据加载失败: {e}")
        return None

# --- 4. 侧边栏交互 ---
df = load_and_pivot_data()

with st.sidebar:
    st.header("📍 位置与半径")
    addr_input = st.text_input("中心地址", "Paris")
    home_coords = get_coords_from_address(addr_input) or (48.8566, 2.3522)
    radius_km = st.slider("搜索半径 (km)", 1, 50, 10)

    if df is not None:
        st.markdown("---")
        st.header("🎯 语种筛选")
        m = df.attrs['menus']
        sel_lv1 = st.selectbox("语言一 (LV1)", m['lv1'], index=m['lv1'].index("Anglais") if "Anglais" in m['lv1'] else 0)
        sel_lv2 = st.selectbox("语言二 (LV2)", ["不限"] + m['lv2'])
        sel_lca = st.selectbox("语言三 (LCA)", ["不限"] + m['lca'])

        st.markdown("---")
        st.header("📊 其他条件")
        c = df.attrs['config']
        all_sects = df[c['sect']].unique().tolist()
        sel_sects = st.multiselect("学校性质", all_sects, default=all_sects)
        ips_range = st.slider("IPS 评分", float(df['final_ips'].min()), float(df['final_ips'].max()), (float(df['final_ips'].min()), float(df['final_ips'].max())))

# --- 5. 过滤逻辑 ---
if df is not None:
    c = df.attrs['config']
    df['dist'] = df.apply(lambda r: geodesic(home_coords, (r['final_lat'], r['final_lon'])).km, axis=1)
    
    # 构建筛选遮罩
    mask = (df['dist'] <= radius_km) & \
           (df['final_ips'] >= ips_range[0]) & \
           (df['final_ips'] <= ips_range[1]) & \
           (df[c['sect']].isin(sel_sects))
    
    mask &= df['lv1_list'].apply(lambda x: sel_lv1 in x)
    if sel_lv2 != "不限": mask &= df['lv2_list'].apply(lambda x: sel_lv2 in x)
    if sel_lca != "不限": mask &= df['lca_list'].apply(lambda x: sel_lca in x)
    
    res = df[mask].sort_values("dist").copy()

    # --- 6. 页面展示 ---
    st.title("🏫 法国中学智能选择系统")
    
    # A. 地图展示 (核心修复：使用不需要 Token 的底图)
    st.subheader("🗺️ 地理分布图 (🔵家 🟢公立 🔴私立)")
    
    # 预处理显示文本
    res['lv1_str'] = res['lv1_list'].apply(lambda x: ", ".join(x))
    res['lv2_str'] = res['lv2_list'].apply(lambda x: ", ".join(x))
    res['lca_str'] = res['lca_list'].apply(lambda x: ", ".join(x))

    view_state = pdk.ViewState(latitude=home_coords[0], longitude=home_coords[1], zoom=11)
    
    school_layer = pdk.Layer(
        "ScatterplotLayer", res,
        get_position=["final_lon", "final_lat"],
        get_color="marker_color",
        get_radius=200,
        pickable=True
    )
    
    home_layer = pdk.Layer(
        "ScatterplotLayer", pd.DataFrame([{"ln": home_coords[1], "lt": home_coords[0]}]),
        get_position=["ln", "lt"],
        get_color=[0, 100, 255, 255],
        get_radius=400
    )

    # 关键点：map_style 使用简单的 carto 样式，避免白屏
    st.pydeck_chart(pdk.Deck(
        layers=[school_layer, home_layer],
        initial_view_state=view_state,
        map_style="light", # 备选："mapbox://styles/mapbox/light-v9" 但通常需要 token
        tooltip={
            "html": "<b>{"+c['name']+"}</b><br/>地址: {"+c['addr']+"}<br/>LV1: {lv1_str}<br/>LV2: {lv2_str}",
            "style": {"color": "white"}
        }
    ))

    # B. 结果表格
    st.markdown("---")
    st.subheader(f"📋 筛选清单 (共 {len(res)} 所)")
    disp_cols = [c['name'], c['sect'], 'final_ips', 'dist', 'lv1_str', 'lv2_str', 'lca_str']
    st.dataframe(
        res[disp_cols].rename(columns={c['name']: '学校', c['sect']: '性质', 'final_ips': 'IPS', 'dist': '距离(km)'}),
        use_container_width=True, hide_index=True, height=400
    )

    if not res.empty:
        st.download_button("📥 导出结果", res.to_csv(index=False).encode('utf-8-sig'), "results.csv")
else:
    st.info("请在 GitHub 仓库中确保包含数据文件并在侧边栏输入地址。")


