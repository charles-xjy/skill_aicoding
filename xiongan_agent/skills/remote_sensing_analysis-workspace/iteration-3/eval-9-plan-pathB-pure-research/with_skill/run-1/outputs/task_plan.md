```json
{
  "tasks": [
    {
      "id": 1,
      "description": "搜索雄安新区总体规划及核心政策文件",
      "query": "雄安新区总体规划 政策文件",
      "agent": "search_agent"
    },
    {
      "id": 2,
      "description": "搜索雄安新区重点片区规划与建设进展",
      "query": "雄安新区 重点片区 建设进展",
      "agent": "search_agent"
    },
    {
      "id": 3,
      "description": "搜索雄安新区产业引入与创新发展政策",
      "query": "雄安新区 产业 创新发展 政策",
      "agent": "search_agent"
    },
    {
      "id": 4,
      "description": "综合政策与规划信息，输出雄安新区总体发展与政策梳理报告",
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
    "intent": "梳理雄安新区的总体规划和主要政策文件"
  },
  "reasoning": "用户明确要求梳理雄安新区的总规和政策，且指定不需要卫星图。因此选择路径B（纯信息研究）。任务顺序为先搜索总体规划与核心政策，再搜索重点片区与建设进展，最后搜索产业与创新政策，最后由analysis_agent综合所有搜索报告生成最终分析。"
}
```