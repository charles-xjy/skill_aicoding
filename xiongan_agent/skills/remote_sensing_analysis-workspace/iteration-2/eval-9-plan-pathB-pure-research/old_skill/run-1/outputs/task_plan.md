```json
{
  "tasks": [
    {
      "id": 1,
      "description": "搜索雄安新区总体规划核心内容与政策框架",
      "query": "雄安新区总体规划 政策文件 核心内容",
      "agent": "search_agent"
    },
    {
      "id": 2,
      "description": "搜索雄安新区重点产业发展政策与人才引进举措",
      "query": "雄安新区 产业发展政策 人才引进 措施",
      "agent": "search_agent"
    },
    {
      "id": 3,
      "description": "搜索雄安新区基础设施建设与公共服务配套政策",
      "query": "雄安新区 基础设施 公共服务 配套政策",
      "agent": "search_agent"
    },
    {
      "id": 4,
      "description": "综合多份政策搜索结果，梳理雄安新区总体发展与政策体系",
      "agent": "analysis_agent"
    }
  ],
  "extracted": {
    "location": "雄安新区",
    "years": [],
    "needs_image": false,
    "intent": "梳理雄安新区总体规划和主要政策文件"
  },
  "reasoning": "用户明确要求梳理雄安新区的总体规划和主要政策文件，且明确指定'不用看卫星图'，属于纯信息研究需求。因此选择路径 B（纯信息研究）。为了全面覆盖'总体规划'与'主要政策'，规划了三个不同侧重点的搜索：①总体规划与核心政策框架；②产业与人才政策；③基建与公服配套政策。最后由 analysis_agent 综合整合，输出结构化分析报告。"
}
```