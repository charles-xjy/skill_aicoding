{
  "task_list": [
    {
      "id": 1,
      "agent": "search_agent",
      "description": "搜索雄安新区近年来的官方建设进展报告、重大基础设施项目清单及规划更新文件，特别是涉及空间布局调整的政策和新闻。",
      "output_key": "xiongan_construction_status"
    },
    {
      "id": 2,
      "agent": "image_agent",
      "description": "获取雄安新区关键区域（如启动区、容东片区、雄东片区）在2017年、2020年、2023年和2026年的多期卫星遥感影像数据，用于对比地表覆盖变化和建筑密度。",
      "output_key": "xiongan_satellite_images"
    },
    {
      "id": 3,
      "agent": "analysis_agent",
      "description": "结合搜索到的建设文本信息与卫星影像数据，进行空间演变分析。重点对比不同年份的建成区面积、道路网络扩展情况及绿地水体变化，并生成一份综合分析报告，展示雄安的空间变化趋势。",
      "output_key": "spatial_change_analysis_report"
    }
  ]
}