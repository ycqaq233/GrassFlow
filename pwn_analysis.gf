// PWN 二进制文件分析工作流
// 使用 GDB 调试器对 pwn 文件进行多层次分析

component file_analyzer {
  system_prompt: "你是一个二进制文件分析专家。使用 file、checksec、readelf 等工具分析给定的二进制文件，输出文件的架构、保护机制、链接方式等基本信息。"
  port input filepath: string "待分析文件的路径"
  port output result: object "文件分析结果，包含架构、保护机制等信息"
  model default: "gpt-4"
  permission allow: [shell, read]
}

component gdb_analyzer {
  system_prompt: |-
    你是一个 GDB 调试专家。使用 GDB 对给定的二进制文件进行深入分析：
    1. 启动 GDB 调试会话
    2. 查看函数/符号信息
    3. 反汇编关键区域（入口点、main函数等）
    4. 分析栈帧、调用约定
    5. 识别潜在的漏洞点（栈溢出、格式化字符串等）
    输出详细的分析报告。
  port input filepath: string "待调试分析的二进制文件路径"
  port input basic_info: object "来自 file_analyzer 的基础文件信息"
  port output result: object "GDB 深度分析结果，包含反汇编、漏洞分析等"
  model default: "gpt-4"
  permission allow: [shell, read]
  // 使用 mcp_gdb-debugger 系列工具
}

component report_generator {
  system_prompt: "你是一个安全报告撰写专家。综合文件分析、GDB 调试分析等结果，生成一份结构化的 PWN 分析报告，包含：漏洞类型、利用思路、关键地址/偏移量、缓解措施等。以中文输出。"
  port input file_info: object "文件基础信息"
  port input gdb_result: object "GDB深度分析结果"
  port output report: string "完整的PWN分析报告"
  model default: "gpt-4"
  permission allow: [write]
}

workflow pwn_analysis {
  agent file_check {
    model: "gpt-4"
    prompt: |-
      分析文件 /root/Code/pwn/pwn。
      1. 运行 `file /root/Code/pwn/pwn` 查看文件类型
      2. 使用 `checksec` 或 `readelf -h /root/Code/pwn/pwn` 查看保护机制
      3. 使用 `readelf -s /root/Code/pwn/pwn` 查看符号表
      输出结构化的文件基础信息。
    permission allow: [shell, read]
  }

  agent gdb_deep_analysis use gdb_analyzer {
    filepath: "/root/Code/pwn/pwn"
  }

  agent final_report use report_generator

  file_check -> gdb_deep_analysis
  file_check -> final_report
  gdb_deep_analysis -> final_report
}
