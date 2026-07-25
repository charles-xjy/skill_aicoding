```json
{
  "tasks": [
    {
      "id": 1,
      "description": "搜索雄安新区总体规划核心内容及政策批复文件",
      "query": "雄安新区总体规划 政策文件 批复",
      "agent": "search_agent"
    },
    {
      "id": 2,
      "description": "搜索雄安新区重点建设进展与产业导入情况",
      "query": "雄安新区 重点建设 产业导入 进展",
      "agent": "search_agent"
    },
    {
      "id": 3,
      "description": "综合搜索报告，梳理雄安新区政策体系与发展脉络",
      "agent": "analysis_agent"
    }
  ],
  "extracted": {
    "location": "雄安新区",
    "years": [
      2021,
      2026
    ],
    "needs_image": false,
    "intent": "政策规划解读与总体发展梳理"
  },
  "reasoning": "用户明确要求梳理雄安新区的总体规划和政策文件，且指定'不用看卫星图'，因此选择路径B（纯信息研究）。任务包括：1. 搜索核心规划与政策文本；2. 搜索建设进展与产业情况以丰富内容维度；3. 由analysis_agent综合生成最终报告。"
}
```