{
  "task_list": [
    {
      "step": 1,
      "agent": "search_agent",
      "description": "搜索雄安新区总体规划（2018-2035年）的官方发布内容、核心定位、空间布局及主要发展目标。",
      "output_key": "xiongan_master_plan_info"
    },
    {
      "step": 2,
      "agent": "search_agent",
      "description": "搜索中共中央、国务院关于支持雄安新区建设的重大政策文件，以及国家部委发布的配套专项政策（如土地、金融、人才引进等）。",
      "output_key": "policy_documents"
    },
    {
      "step": 3,
      "agent": "search_agent",
      "description": "搜索雄安新区近年来的实施进展、试点改革经验及最新动态补充信息。",
      "output_key": "recent_developments"
    },
    {
      "step": 4,
      "agent": "analysis_agent",
      "inputs": [
        "xiongan_master_plan_info",
        "policy_documents",
        "recent_developments"
      ],
      "description": "整合总体规划内容与政策文件要点，梳理雄安新区的核心规划逻辑、政策体系架构及实施成效，生成综合梳理报告。"
    }
  ]
}