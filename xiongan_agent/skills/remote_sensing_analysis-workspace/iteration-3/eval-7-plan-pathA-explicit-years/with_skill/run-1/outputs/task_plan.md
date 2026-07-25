```json
{
  "tasks": [
    {
      "id": 1,
      "description": "获取北邮沙河校区在[2020, 2025]的卫星影像",
      "years": [2020, 2025],
      "agent": "image_agent"
    },
    {
      "id": 2,
      "description": "搜索北邮沙河校区官方规划与总体建设布局",
      "query": "北邮沙河校区 官方规划 总体布局",
      "agent": "search_agent"
    },
    {
      "id": 3,
      "description": "搜索北邮沙河校区近期重点建设项目进展",
      "query": "北邮沙河校区 建设项目 进展 竣工",
      "agent": "search_agent"
    },
    {
      "id": 4,
      "description": "搜索北邮沙河校区配套设施及师生评价",
      "query": "北邮沙河校区 配套设施 师生评价",
      "agent": "search_agent"
    },
    {
      "id": 5,
      "description": "综合卫星影像与搜索报告，输出最终分析报告",
      "agent": "analysis_agent"
    }
  ],
  "extracted": {
    "location": "北京邮电大学沙河校区",
    "years": [
      2020,
      2025
    ],
    "needs_image": true,
    "intent": "空间形态变化与整体发展评估"
  },
  "reasoning": "用户明确要求对比2020和2025年的卫星变化图，并询问发展情况，属于典型的空间形态变化分析，因此必须调用image_agent获取卫星影像。搜索角度选取了官方规划、项目进展和配套设施，以全面覆盖校区建设与发展内容。任务顺序遵循先影像后搜索再综合的分析逻辑。"
}
```