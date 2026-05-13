from pathlib import Path

import ee
import requests
import os

from langchain_core.tools import tool
from tqdm import tqdm


# --- 3. 定义带进度的下载函数 ---
def download_image_with_year(name, lon, lat, year):
    # --- 1. 初始化 ---
    # 1. 触发认证流程
    os.environ['HTTP_PROXY'] = 'http://127.0.0.1:7897'
    os.environ['HTTPS_PROXY'] = 'http://127.0.0.1:7897'
    try:
        ee.Authenticate(auth_mode='notebook')
        
        ee.Initialize(project="ee-charles1xjy")
        print("GEE 初始化成功！")
    except Exception as e:
        print(f"认证出错: {e}")

    # 2. 初始化 API
    # 注意：如果你使用的是 Google Cloud Project，请填入你的项目 ID
    # ee.Initialize(project='your-project-id')

    # --- 2. 设置路径 ---
    base_dir = Path("/home/charles/mycode/multiagent/xiongan_agent/image_agent")
    target_folder = os.path.join(base_dir, "Google_earth_image")

    if not os.path.exists(target_folder):
        os.makedirs(target_folder)
        print(f"✅ 已创建文件夹: {target_folder}")
    # 1. 修改坐标：美国加州奥克兰 甲骨文球馆
    # 注意：西经是负数！
    # lon, lat = -122.2030, 37.7503

    # 替换为大通中心的坐标
    # $$像素尺寸(Dimensions) = \frac{(Buffer * 2)}{每个像素代表的实际距离(Scale)}$$
    # buffer(400) 意味着提取 800x800米 的区域，刚好框住球馆和停车场
    roi = ee.Geometry.Point([lon, lat]).buffer(1250).bounds()

    # NAIP 数据不是每年都有（通常一个州每2-3年拍一次）
    # 所以我们把时间范围放宽到该年份往前推2年，确保能拿到图
    start_date = f"{year - 2}-01-01"
    end_date = f"{year}-12-31"

    try:
        # 2. 修改卫星：换成超高清的 NAIP 数据集
        collection = (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(roi)
            .filterDate(start_date, end_date)
            .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 10))
            .sort("system:time_start", False)
        )  # 优先取最新的

        count = collection.size().getInfo()
        if count == 0:
            return f"跳过: {year} 年附近没有找到 NAIP 影像。"

        # 现在改成这样：把所有相关的图拼起来
        # 使用中值合成（Median）比 Mosaic 更能有效去除残余的云影
        dataset = collection.median()

        # 3. 修改波段名称和显示范围
        # 哨兵2号：B4=R, B3=G, B2=B。数值范围 0-3000 左右
        vis_params = {
            "bands": ["B4", "B3", "B2"],
            "min": 0,
            "max": 3500,  # 可以根据亮度微调这个值
            "gamma": 1.4  # 稍微增加伽马值让图片色彩更鲜艳
        }
        # 4. 获取 URL
        url = dataset.visualize(**vis_params).getThumbURL(
            {
                "region": roi,
                "dimensions": 256,  # 你要求的 512
                "format": "jpg"
            }
        )
        file_name = f"{name}_{year}.jpg"
        save_path = os.path.join(target_folder, file_name)

        r = requests.get(url, timeout=60)
        if r.status_code == 200:
            with open(save_path, "wb") as f:
                f.write(r.content)
            return f"成功: {file_name}"
        else:
            return f"失败: {year} 年请求返回状态码 {r.status_code}"

    except Exception as e:
        return f"异常: {year} 年处理出错 -> {str(e)}"


@tool
def tool_download_image(name: str, years_to_download: list[int], target_lon: float, target_lat: float):
    """
    获取指定地点在多个年份的卫星影像，并返回保存的文件列表。

    参数:
    - name: 地点标识符，用于文件命名。
    - years_to_download: 需要下载的年份列表。
    - target_lon, target_lat: 目标的经纬度坐标。

    返回:
    - 一个包含已保存文件详细信息的 JSON 列表，供后续分析调用。
    """
    print(f"\n🚀 开始下载任务：{name}...")

    downloaded_files = []  # 🌟 用于存储成功的文件信息

    with tqdm(total=len(years_to_download), desc="下载进度", unit="img") as pbar:
        for year in years_to_download:
            pbar.set_postfix_str(f"处理 {year}")

            # 调用底层下载逻辑
            result_msg = download_image_with_year(name, target_lon, target_lat, year)
            current_script_path = os.path.abspath(__file__)
            # 获取 image_agent 目录的路径 (即 tool 文件夹的上一层)
            image_agent_dir = os.path.dirname(os.path.dirname(current_script_path))

            # 拼接目标文件夹
            fianl_folder = os.path.join(image_agent_dir, "Google_earth_image")

            # 如果成功，构造结构化数据
            if "成功" in result_msg:
                file_name = f"{name}_{year}.jpg"

                downloaded_files.append({
                    "year": year,
                    "file_name": file_name,
                    "path": os.path.join(fianl_folder, file_name),
                    "status": "success"
                })

            tqdm.write(result_msg)
            pbar.update(1)

    # 🌟 返回给 Agent 的关键内容
    return {
        "description": f"成功下载了 {name} 在 {len(downloaded_files)} 个年份的影像。",
        "files": downloaded_files
    }


def main():
    years_to_download = [2015, 2025]
    target_lon = 116.358103
    target_lat = 39.962796
    a = tool_download_image.invoke({
        "name": "北京邮电大学",
        "years_to_download": years_to_download,
        "target_lon": target_lon,
        "target_lat": target_lat
    })
    print(a)


if __name__ == "__main__":
    main()
