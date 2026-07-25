{
  "tasks": [
    {
      "id": 1,
      "description": "获取雄安新区2019-2025年期间的卫星影像",
      "years": [
        2019,
        2021,
        2023,
        2025
      ],
      "agent": "image_agent"
    },
    {
      "id": 2,
      "description": "搜索雄安新区总体城市设计与核心启动区规划布局",
      "query": "雄安新区 城市规划 核心启动区 布局",
      "agent": "search_agent"
    },
    {
      "id": 3,
      "description": "搜索雄安新区重点基础设施与公服设施建设进展",
      "query": "雄安新区 基础设施建设 公共服务 进展",
      "agent": "search_agent"
    },
    {
      "id": 4,
      "description": "搜索雄安新区生态建设与绿色生态屏障发展情况",
      "query": "雄安新区 生态建设 绿色屏障 白洋淀",
      "agent": "search_agent"
    },
    {
      "id": 5,
      "description": "综合卫星影像与搜索报告，输出最终分析报告",
      "agent": "analysis_agent"
    }
  ],
  "extracted": {
    "location": "雄安新区",
    "years": [
      2019,
      2021,
      2023,
      2025
    ],
    "needs_image": true,
    "intent": "城市新区空间形态演变与建设进展评估"
  },
  "reasoning": "用户明确询问'空间上的变化'且涉及'这几年'，符合路径A（完整分析）条件。需调用image_agent获取多年卫星影像以对比空间形态；同时规划3次search_agent分别关注规划布局、基础设施和生态环境，以全面解读建设现状。最后由analysis_agent融合影像与文本信息输出报告。"
}