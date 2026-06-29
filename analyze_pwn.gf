workflow analyze_pwn {
  agent basic_info {
    model: "gpt-4"
    prompt: |
      你是 GDB 调试分析专家。请对 /root/Code/pwn/pwn 这个二进制文件进行基本分析。

      执行以下步骤:
      1. `file /root/Code/pwn/pwn` 确认文件类型
      2. `readelf -h /root/Code/pwn/pwn` 查看 ELF 头
      3. `readelf -l /root/Code/pwn/pwn` 查看程序头
      4. `readelf -S /root/Code/pwn/pwn` 查看节区
      5. `strings /root/Code/pwn/pwn` 查看关键字符串
      6. `objdump -d /root/Code/pwn/pwn` 反汇编
      7. `readelf -d /root/Code/pwn/pwn` 查看动态段

      输出所有结果和你的分析。
    `
    permission allow: [read, glob, grep]
  }

  agent gdb_deep_analysis {
    model: "gpt-4"
    prompt: |
      你是 GDB 逆向分析专家。请启动 GDB 对 /root/Code/pwn/pwn 进行深度动态分析。

      步骤:
      1. 启动 GDB: `gdb -q /root/Code/pwn/pwn`
      2. 查看入口: `info files` 找到 entry point
      3. 设断点: `break *entry_point_address`
      4. 运行: `run`
      5. 停在入口后:
         - `info registers` 查看寄存器
         - `info proc mappings` 查看内存映射  
         - `x/50i $pc` 查看入口代码
      6. 单步: `stepi` 执行几步并观察
      7. `info functions` 查看函数
      8. `checksec` 或手动检查安全保护

      输出所有 GDB 输出和你的分析结论。
    `
    permission allow: [read, glob, grep]
  }

  (basic_info, gdb_deep_analysis) -> report_agent

  agent report_agent {
    model: "gpt-4"
    prompt: |
      你是 PWN 安全分析报告生成专家。

      汇总前面两个 Agent 的分析结果，生成完整的二进制安全分析报告。

      ## 📦 文件概览
      ## 🔒 安全保护机制  
      ## 🏗️ 程序结构(入口点、节区、关键代码)
      ## 🔍 反汇编关键发现
      ## ⚡ 运行时行为
      ## 🎯 安全评估与利用建议
    `
    permission allow: [read]
  }
}
