// Pwn 二进制分析工作流
// 使用 GDB 对 /root/Code/pwn/pwn 进行多角度安全分析

component gdb_analyzer {
  system_prompt: |-
    你是一个二进制安全分析专家。你需要使用 gdb-debugger MCP 工具对目标程序进行分析。
    
    可用的 gdb-debugger MCP 工具：
    - mcp_gdb-debugger_start_debugging: 启动 GDB 调试会话
    - mcp_gdb-debugger_send_gdb_command: 发送 GDB 命令
    - mcp_gdb-debugger_run_shell_command: 在宿主机执行 shell 命令
    - mcp_gdb-debugger_interrupt: 中断程序
    - mcp_gdb-debugger_stop_debugging: 停止调试会话

    分析目标: /root/Code/pwn/pwn (32-bit i386 ELF)
    
    请执行以下分析步骤：
    1. 用 shell 命令检查文件: `file /root/Code/pwn/pwn`, `checksec --file=/root/Code/pwn/pwn` 或 `readelf -h`, `readelf -l`, `readelf -S`
    2. 启动 GDB: 使用 start_debugging 工具
    3. 在 GDB 中执行: info functions, info file, disassemble entry point
    4. 尝试反汇编 main 或关键函数
    5. 检查安全机制: 是否有 canary, NX, PIE, RELRO
    
    分析完成后，输出详细的分析报告，包括：
    - 文件基本信息
    - 安全机制分析
    - 函数入口和关键代码
    - 潜在漏洞分析

  port input target_file: string "目标二进制文件路径"
  port output analysis_report: string "分析报告"
  model default: "gpt-4o-mini"
  permission allow: [mcp_gdb-debugger_run_shell_command, mcp_gdb-debugger_start_debugging, mcp_gdb-debugger_send_gdb_command, mcp_gdb-debugger_interrupt, mcp_gdb-debugger_stop_debugging]
}

component report_writer {
  system_prompt: |-
    你是一个安全分析报告总结专家。
    你需要接收多个分析报告，将它们合并成一份结构完整、条理清晰的总报告。
    
    报告格式要求：
    1. 文件基本信息 (文件类型、大小、架构等)
    2. 安全机制摘要 (NX, PIE, RELRO, Stack Canary, ASLR等)
    3. 关键函数和代码分析
    4. 潜在漏洞分析
    5. 建议的利用思路
    
    请保持技术准确性，使用中文输出。

  port input gdb_report: string "GDB 分析结果"
  port output final_report: string "最终综合分析报告"
  model default: "gpt-4o-mini"
  permission allow: []
}

workflow pwn_workflow {
  // Step 1: 用 GDB 分析二进制文件
  agent gdb_analysis {
    model: "gpt-4o-mini"
    use: gdb_analyzer
    prompt: "请分析目标文件: /root/Code/pwn/pwn"
    permission allow: [mcp_gdb-debugger_run_shell_command, mcp_gdb-debugger_start_debugging, mcp_gdb-debugger_send_gdb_command, mcp_gdb-debugger_interrupt, mcp_gdb-debugger_stop_debugging]
  }

  // Step 2: 生成最终报告
  agent final_report {
    model: "gpt-4o-mini"
    use: report_writer
    prompt: "根据 GDB 分析结果生成最终安全分析报告"
  }

  // 顺序执行
  gdb_analysis -> final_report
}
