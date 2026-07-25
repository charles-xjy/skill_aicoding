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
    "intent": "空间形态变化与整体发展评估"
  },
  "reasoning": "用户明确提到需要“2020和2025的卫星变化图”来介绍“发展”，满足包含卫星影像的条件。因此选择路径A（完整分析）。首先通过image_agent获取两年份的卫星影像以直观展示空间变化；随后通过3次search_agent分别从官方规划、建设进展和配套设施三个角度搜集文字信息，以辅助解读影像变化的具体内涵；最后由analysis_agent融合影像与文本信息输出综合报告。"
}