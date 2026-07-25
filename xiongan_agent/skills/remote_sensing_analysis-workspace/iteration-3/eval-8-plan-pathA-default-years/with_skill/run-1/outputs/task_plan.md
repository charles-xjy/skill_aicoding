```json
{
  "tasks": [
    {
      "id": 1,
      "description": "获取雄安新区在[2021, 2026]的卫星影像",
      "years": [
        2021,
        2026
      ],
      "agent": "image_agent"
    },
    {
      "id": 2,
      "description": "搜索雄安新区整体空间形态演变与城市建设进展",
      "query": "雄安新区 空间演变 城市建设 2021-2026",
      "agent": "search_agent"
    },
    {
      "id": 3,
      "description": "搜索雄安新区核心片区（如启动区、容东）建设成果",
      "query": "雄安新区 启动区 容东片区 建设成果 交付",
      "agent": "search_agent"
    },
    {
      "id": 4,
      "description": "搜索雄安新区基础设施配套与生态建设情况",
      "query": "雄安新区 基础设施 生态建设 配套完善",
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
      2026
    ],
    "needs_image": true,
    "intent": "空间形态变化评估"
  },
  "reasoning": "用户关注雄安新区的空间变化，明确需要对比建设成果。根据规则，未提及年份取[2021, 2026]。因涉及空间变化对比，需调用image_agent获取卫星影像。随后通过search_agent分别从整体演变、核心片区建设、基础设施配套三个角度收集文本信息，最后由analysis_agent融合影像与文本进行综合评估。"
}
```