```json
{
  "tasks": [
    {
      "id": 1,
      "description": "获取雄安新区在[2021, 2026]的卫星影像",
      "years": [2021, 2026],
      "agent": "image_agent"
    },
    {
      "id": 2,
      "description": "搜索雄安新区官方总体规划与片区开发布局",
      "query": "雄安新区 总体规划 片区开发",
      "agent": "search_agent"
    },
    {
      "id": 3,
      "description": "搜索雄安新区重点建设项目与城市配套进展",
      "query": "雄安新区 重点工程 配套设施 建设进展",
      "agent": "search_agent"
    },
    {
      "id": 4,
      "description": "搜索雄安新区人口产业导入与城市发展成效",
      "query": "雄安新区 人口产业 入驻情况 发展成果",
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
    "years": [2021, 2026],
    "needs_image": true,
    "intent": "空间形态变化与整体建设评估"
  },
  "reasoning": "用户明确询问“空间上的变化”，符合需要卫星影像的条件。当前年份为2026年，未提及具体年份，默认取[2021, 2026]进行首尾对比。路径选择A（完整分析），先获取影像，再通过搜索获取规划、建设进度及产业人口数据，最后由analysis_agent结合影像与文本进行综合分析。"
}
```