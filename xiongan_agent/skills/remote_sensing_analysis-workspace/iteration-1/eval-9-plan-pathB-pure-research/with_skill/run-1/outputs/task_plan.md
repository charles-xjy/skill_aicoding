{
  "tasks": [
    {
      "id": 1,
      "description": "搜索雄安新区总体规划及核心政策文件",
      "query": "雄安新区 总体规划 政策文件",
      "agent": "search_agent"
    },
    {
      "id": 2,
      "description": "搜索雄安新区建设进展与重点项目落地情况",
      "query": "雄安新区 建设进展 重点项目",
      "agent": "search_agent"
    },
    {
      "id": 3,
      "description": "搜索雄安新区产业导入与人口引入情况",
      "query": "雄安新区 产业导入 人口引入",
      "agent": "search_agent"
    },
    {
      "id": 4,
      "description": "综合搜索结果，输出雄安新区总体规划与政策研究报告",
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
    "intent": "政策规划解读"
  },
  "reasoning": "用户明确要求梳理雄安新区总体规划和主要政策文件，且指定不使用卫星图，因此选择路径B（纯信息研究）。根据城市开发/新区意图，选取了官方规划/政策、建设进展、产业/人口引入三个搜索角度，最后通过analysis_agent整合信息输出报告。"
}