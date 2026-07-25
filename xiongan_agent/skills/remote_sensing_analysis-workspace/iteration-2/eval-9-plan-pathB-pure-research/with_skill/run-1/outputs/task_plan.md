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
      "description": "搜索雄安新区产业发展与人才引进配套政策",
      "query": "雄安新区 产业发展 人才政策",
      "agent": "search_agent"
    },
    {
      "id": 3,
      "description": "搜索雄安新区基础设施建设与公共服务规划",
      "query": "雄安新区 基础设施 公共服务 规划",
      "agent": "search_agent"
    },
    {
      "id": 4,
      "description": "综合各维度搜索结果，梳理雄安新区总体规划与政策体系",
      "agent": "analysis_agent"
    }
  ],
  "extracted": {
    "location": "雄安新区",
    "years": [2021, 2026],
    "needs_image": false,
    "intent": "政策规划解读"
  },
  "reasoning": "用户明确要求梳理雄安新区的总体规划及主要政策文件，且明确说明‘不用看卫星图’，因此选择路径B（纯信息研究）。搜索角度选取官方总体规划文件、产业与人才政策、以及基础设施与公共服务规划三个维度，以全面覆盖用户关心的‘总体规划’与‘主要政策’内容，最后由analysis_agent整合输出。"
}
```