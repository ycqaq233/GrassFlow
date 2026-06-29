// PWN 二进制分析工作流 - 使用 GDB 调试器 MCP 工具
// 模型: DeepSeek V4 Flash

component gdb_analyzer {
  system_prompt: |-
    你是一个 GDB 逆向分析专家。请使用 gdb-debugger MCP 工具对给定的二进制文件进行深入分析。

    分析步骤（严格按此顺序执行）：
    1. 用 `gdb-debugger_start_debugging` 启动 GDB 会话
    2. 用 `gdb-debugger_send_gdb_command` 发送以下命令逐一分析：
       - `info file` - 查看文件头信息
       - `info functions` - 查看函数列表(即使stripped也会显示动态链接函数)
       - `info variables` - 查看全局变量
       - `checksec` 或手动检查安全特性
       - `info proc mappings` - 查看内存映射
       - `disassemble _start` - 反汇编入口点
       - `x/10i $eip` - 查看指令
       - `info registers` - 查看寄存器信息
    3. 用 `gdb-debugger_stop_debugging` 结束会话
    4. 撰写完整分析报告，包括：文件基本信息、安全特性、函数分析、潜在漏洞

    每个命令执行后，等待输出结果再执行下一个。认真分析每个输出。

  port input target_path: object "包含 target_path 字段的对象"
  port output report: object "分析报告"
  output result: object "analysis_results"

  model default: "deepseek-v4-flash"
  permission allow: [mcp_gdb-debugger_start_debugging, mcp_gdb-debugger_send_gdb_command, mcp_gdb-debugger_stop_debugging, mcp_gdb-debugger_interrupt, mcp_gdb-debugger_run_shell_command]
}

workflow pwn_analysis_workflow {
  // Step 1: GDB 分析
  agent analyzer use gdb_analyzer {
    prompt: "请对二进制文件 /root/Code/pwn/pwn 进行完整的 GDB 逆向分析"
  }
}
