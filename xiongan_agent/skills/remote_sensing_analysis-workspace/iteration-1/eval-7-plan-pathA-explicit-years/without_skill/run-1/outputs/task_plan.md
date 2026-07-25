{
  "task_list": [
    {
      "task_id": 1,
      "agent": "image_agent",
      "description": "获取北京邮电大学沙河校区2020年的卫星影像",
      "parameters": {
        "location": "北京邮电大学沙河校区",
        "date": "2020-01-01"
      }
    },
    {
      "task_id": 2,
      "agent": "image_agent",
      "description": "获取北京邮电大学沙河校区2025年的卫星影像",
      "parameters": {
        "location": "北京邮电大学沙河校区",
        "date": "2025-01-01"
      }
    },
    {
      "task_id": 3,
      "agent": "search_agent",
      "description": "搜索北邮沙河校区2020年至2025年间的重要建设规划、新建楼群及科研设施落成新闻",
      "parameters": {
        "query": "北邮沙河校区 2020-2025 建设发展 新楼 科研设施"
      }
    },
    {
      "task_id": 4,
      "agent": "analysis_agent",
      "description": "结合卫星影像变化与网络搜索资料，分析北邮沙河校区近几年的基础设施变化及发展概况",
      "parameters": {
        "input_data": [
          "task_1_result",
          "task_2_result",
          "task_3_result"
        ]
      }
    }
  ]
}