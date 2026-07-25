{
  "tasks": [
    {
      "id": 1,
      "description": "获取雄安新区在[2021, 2022, 2023, 2024, 2025, 2026]的卫星影像",
      "years": [
        2021,
        2022,
        2023,
        2024,
        2025,
        2026
      ],
      "agent": "image_agent"
    },
    {
      "id": 2,
      "description": "搜索雄安新区官方规划与总体布局进展",
      "query": "雄安新区 官方规划 总体布局",
      "agent": "search_agent"
    },
    {
      "id": 3,
      "description": "搜索雄安新区重点建设项目与基础设施落地情况",
      "query": "雄安新区 重点项目 基础设施 建设",
      "agent": "search_agent"
    },
    {
      "id": 4,
      "description": "搜索雄安新区产业导入与人口居住配套发展",
      "query": "雄安新区 产业引入 人口 居住配套",
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
      2021,
      2022,
      2023,
      2024,
      2025,
      2026
    ],
    "needs_image": true,
    "intent": "分析雄安新区的空间形态变化与建设进展"
  },
  "reasoning": "用户明确提到‘看看空间上的变化’，这直接触发了需要卫星影像的条件。根据规则，需先调用 image_agent 获取多年的卫星影像以展示空间演变。同时，为了全面回答‘建设得怎么样了’，需要搜索官方规划、重点项目建设以及产业人口配套等方面的信息。因此，选择路径 A（完整分析），顺序为 image_agent → search_agent (3次) → analysis_agent。"
}