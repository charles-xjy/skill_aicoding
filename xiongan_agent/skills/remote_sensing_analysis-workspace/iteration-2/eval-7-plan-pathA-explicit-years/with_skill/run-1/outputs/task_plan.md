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
      "description": "搜索北邮沙河校区官方规划与总体布局",
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
    "intent": "校区建设空间变化与整体发展评估"
  },
  "reasoning": "用户明确要求基于2020和2025年的卫星变化图进行分析，涉及空间形态对比，因此必须使用路径A（完整分析），包含image_agent获取影像。同时需要搜索校区规划、建设进展等信息以支撑文字分析，故安排两次search_agent，最后由analysis_agent整合输出。"
}
```