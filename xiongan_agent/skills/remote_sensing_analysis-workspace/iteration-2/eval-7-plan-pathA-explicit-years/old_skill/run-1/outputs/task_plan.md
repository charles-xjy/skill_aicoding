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
      "description": "搜索北邮沙河校区官方规划与总体布局进展",
      "query": "北邮沙河校区 官方规划 总体布局",
      "agent": "search_agent"
    },
    {
      "id": 3,
      "description": "搜索北邮沙河校区重点新建项目与基础设施",
      "query": "北邮沙河校区 建设项目 进展 竣工",
      "agent": "search_agent"
    },
    {
      "id": 4,
      "description": "搜索北邮沙河校区配套设施与生活保障完善情况",
      "query": "北邮沙河校区 配套设施 宿舍 食堂",
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
    "years": [2020, 2025],
    "needs_image": true,
    "intent": "分析北邮沙河校区2020年至2025年间空间形态变化及整体发展情况"
  },
  "reasoning": "用户明确要求对比2020和2025年的卫星变化图，涉及空间形态和建设用地变化，符合路径A（完整分析）。因此首先调用image_agent获取两年份卫星影像。随后，为了全面解读发展情况，安排三次search_agent搜索：分别关注官方规划与总体布局、具体重点建设工程进展、以及生活配套设施，以结合影像数据提供丰富的文字背景和分析。最后由analysis_agent整合所有信息进行综合评估。"
}
```