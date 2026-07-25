```json
{
  "tasks": [
    {
      "id": 1,
      "description": "获取北邮沙河校区在[2020, 2025]的卫星影像",
      "years": [
        2020,
        2025
      ],
      "agent": "image_agent"
    },
    {
      "id": 2,
      "description": "搜索北邮沙河校区官方规划与建设总体布局",
      "query": "北邮沙河校区 官方规划 总体布局",
      "agent": "search_agent"
    },
    {
      "id": 3,
      "description": "搜索北邮沙河校区重点建设项目进展",
      "query": "北邮沙河校区 建设项目 进展 竣工",
      "agent": "search_agent"
    },
    {
      "id": 4,
      "description": "搜索北邮沙河校区配套设施（宿舍/食堂/体育）",
      "query": "北邮沙河校区 配套设施 宿舍 食堂 体育",
      "agent": "search_agent"
    },
    {
      "id": 5,
      "description": "综合卫星影像与搜索报告，输出最终分析报告",
      "agent": "analysis_agent"
    }
  ],
  "extracted": {
    "location": "北邮沙河校区",
    "years": [
      2020,
      2025
    ],
    "needs_image": true,
    "intent": "空间形态变化 / 整体发展评估"
  },
  "reasoning": "用户明确要求基于2020和2025年的卫星变化图分析发展，涉及多年度空间对比，因此必须选择路径A（完整分析，含卫星影像）。任务顺序为先获取影像，再针对‘规划布局’、‘建设进展’、‘配套设施’三个角度进行搜索，最后由analysis_agent融合影像与文本信息输出报告。"
}
```