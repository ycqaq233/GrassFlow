workflow pwn_binary_analysis {
  // ===== 阶段1: 并行分析二进制文件的各个维度 =====

  agent reverse_engineer {
    model: "gpt-4"
    permission allow: [read, glob, grep, shell]
    system_prompt: "你是一名资深二进制逆向工程师，专门分析 i386 ELF 二进制文件。请基于以下完整反汇编代码和二进制信息，分析该 pwn 程序的关键函数逻辑和漏洞。"

    prompt: |
      ## 二进制文件信息
      - 架构: i386 (32-bit), No PIE (固定基址 0x8048000)
      - 保护: Full RELRO, NX enabled, No canary
      - 入口点: 0x80485a0

      ## 关键字符串
      - "Time's up" (0x8048920)
      - "Correct" (0x804892e)
      - "/dev/urandom" (0x8048937)

      ## 导入函数
      read, signal, alarm, puts, exit, open, strlen, write, setvbuf, memset, sprintf, strncmp

      ## 完整反汇编

      ### 函数 0x804869b - SIGALRM handler
      ```
      0x804869b: push ebp; mov ebp,esp; sub esp,0x8
      0x80486a4: push 0x8048920; call puts@plt  ; "Time's up"
      0x80486b1: push 0x1; call exit@plt
      ```

      ### 函数 0x80486bb - init()
      ```
      0x80486c4: push 0x3c; call alarm@plt    ; 设置60秒定时器
      0x80486d1: push 0x804869b; push 0xe; call signal@plt  ; 注册SIGALRM=14处理器
      ; setvbuf(stdin, NULL, 2, 0), setvbuf(stdout, NULL, 2, 0), setvbuf(stderr, NULL, 2, 0)
      ```

      ### 函数 0x804871f - validate_and_respond(arg1)
      ```
      0x0804871f: push ebp; mov ebp,esp; sub esp,0x58
      0x08048728: push 0x20; push 0x0; lea eax,[ebp-0x4c]; push eax; call memset@plt  ; 清空32字节buf1
      0x0804873b: push 0x20; push 0x0; lea eax,[ebp-0x2c]; push eax; call memset@plt  ; 清空32字节buf2
      0x0804874e: push [ebp+0x8]; push 0x804892a; lea eax,[ebp-0x4c]; push eax; call sprintf@plt  ; 格式化随机数到buf1
      0x08048765: push 0x20; lea eax,[ebp-0x2c]; push eax; push 0x0; call read@plt  ; 读取32字节输入到buf2
      0x08048775: mov [ebp-0xc], eax           ; 保存读取的字节数
      0x0804877e: mov BYTE [ebp+eax*1-0x2c], 0x0  ; 去除换行符
      0x0804878a: call strlen@plt              ; 计算buf2长度
      0x0804879e: call strncmp@plt             ; strncmp(buf2, buf1, strlen(buf2))
      0x080487a8: test eax,eax; jne 0x80487c4
      ; if match:
      0x080487b4: push 0x804892e; push 0x1; call write@plt  ; 写入"Correct\n"(8字节)
      0x080487be: movzx eax, BYTE [ebp-0x25]  ; 返回 buf1[0x27] 处的一个字节 (0x4c-0x25=0x27)
      0x080487c2: jmp 0x80487ce
      ; else:
      0x080487c4: push 0x0; call exit@plt      ; 退出
      0x080487ce: leave; ret
      ```

      ### 函数 0x80487d0 - read_based_on_byte(byte_arg)
      ```
      0x080487d0: push ebp; mov ebp,esp; sub esp,0xf8
      0x080487dc: mov [ebp-0xec], al           ; 保存参数byte
      0x080487e2: cmp BYTE [ebp-0xec], 0x7f    ; 比较是否为0x7f
      0x080487e9: je 0x8048809
      ; if != 0x7f:
      0x080487f2: push eax; lea eax,[ebp-0xe7]; push eax; push 0x0; call read@plt  ; 只读1字节
      ; if == 0x7f:
      0x0804880c: push 0xc8; lea eax,[ebp-0xe7]; push eax; push 0x0; call read@plt  ; 读200字节到[ebp-0xe7]！
      0x08048823: leave; ret
      ```

      ### main 函数 0x8048825
      ```
      0x08048836: call 0x80486bb              ; init() - 设置alarm和信号
      0x08048840: push 0x8048937; call open@plt  ; open("/dev/urandom", 0)
      0x0804884d: mov [ebp-0xc], eax           ; fd
      0x08048859: push 0x4; lea eax,[ebp-0x14]; push eax; push [ebp-0xc]; call read@plt  ; 读4字节随机数
      0x0804886a: mov eax, [ebp-0x14]          ; 4字节随机值
      0x08048871: call 0x804871f              ; validate_and_respond(random_val)
      0x08048879: mov [ebp-0xd], al            ; 保存返回的字节
      0x08048884: call 0x80487d0              ; read_based_on_byte(returned_byte)
      0x08048898: ret
      ```

      ## 分析要求
      请详细分析以下内容：
      1. 程序整体逻辑和流程
      2. 每个关键函数的详细功能
      3. 识别安全漏洞（特别是缓冲区溢出）
      4. 利用思路分析
      5. 格式字符串 0x804892a 的可能内容（sprintf的format字符串）

  }

  agent vulnerability_analyst {
    model: "gpt-4"
    permission allow: [read, glob, grep]
    system_prompt: "你是一名专业的二进制漏洞分析师，专注于CTF pwn方向。请基于逆向工程数据，识别漏洞并给出利用方案。"

    prompt: |
      ## 漏洞分析任务

      ### 程序概况
      - i386 32-bit ELF，No PIE, No Canary, NX enabled, Full RELRO
      - 函数 validate_and_respond(0x804871f): 从 /dev/urandom 读取4字节，用sprintf格式化，要求用户输入匹配，匹配则返回buf[0x27]处的一个字节
      - 函数 read_based_on_byte(0x80487d0): 根据输入的byte决定读取量——若byte==0x7f则读取200字节到栈上

      ### 关键栈布局分析

      **validate_and_respond 的栈帧 (sub esp,0x58):**
      - [ebp-0x4c] = buf1 (32字节) — sprintf写入随机数的字符串表示
      - [ebp-0x2c] = buf2 (32字节) — 用户输入
      - [ebp-0x25] = 返回给调用者的字节 (buf1+0x27)
      - [ebp-0xc] = read返回值

      **read_based_on_byte 的栈帧 (sub esp,0xf8):**
      - [ebp-0xec] = byte_arg (传入的参数)
      - [ebp-0xe7] = 读取数据的缓冲区
      - 当 byte == 0x7f 时，read(0, &buf, 0xc8) 读取最多200字节到 [ebp-0xe7]
      - 缓冲区大小: 从 [ebp-0xe7] 到 [ebp+0x0] 共 0xe7 = 231 字节
      - 读取200字节到该缓冲区，存在溢出风险！
      - 返回地址在 [ebp+0x4]

      ### 分析要求
      1. 分析 validate_and_respond 函数中 sprintf 的格式字符串是什么？结合随机数是4字节整数这一事实分析
      2. 如何通过第一关（猜解/绕过随机数校验）？
      3. 分析 read_based_on_byte 函数中的缓冲区溢出漏洞细节
      4. 计算溢出到返回地址需要的精确偏移量
      5. 由于 NX enabled（不能执行栈上shellcode）且 Full RELRO（不能改GOT），给出完整的ROP利用链思路
      6. 系统中有 libc6_2.31 可用，考虑 ret2libc 方案
      7. 给出完整的 exploit 策略

  }

  agent rop_chain_builder {
    model: "gpt-4"
    permission allow: [read, glob, grep]
    system_prompt: "你是一名 ROP 链构造专家，精通 i386 架构下的 ROP 利用技术。请基于逆向数据构造完整的 ROP 链。"

    prompt: |
      ## ROP 链构造任务

      ### 可用条件
      - 架构: i386 (32-bit)，参数通过栈传递
      - No PIE: 固定地址，可直用 PLT/GOT
      - NX enabled: 不能执行 shellcode
      - Full RELRO: GOT 只读，不能改写 GOT 表
      - No canary: 栈上无 canary 保护

      ### 可用 PLT 函数
      ```
      read@plt:   0x08048530
      signal@plt: 0x08048538
      alarm@plt:  0x08048540
      puts@plt:   0x08048548
      exit@plt:   0x08048558
      open@plt:   0x08048560
      strlen@plt: 0x08048568
      write@plt:  0x08048578
      setvbuf@plt:0x08048580
      memset@plt: 0x08048588
      sprintf@plt:0x08048590
      strncmp@plt:0x08048598
      ```

      ### 可利用的 gadget 查找
      由于没有直接给出 gadgets，需要分析在 .text 段 (0x080485a0-0x08048902) 中可能存在的 ROP gadgets。

      ### 溢出场景
      - 函数 read_based_on_byte(0x80487d0) 中：
      - [ebp-0xe7] 是缓冲区，可写入最多200字节 (0xc8)
      - 从 [ebp-0xe7] 到 [ebp+4] (返回地址) 的距离 = 0xe7 + 4 = 0xeb = 235 字节
      - 但只写入200字节，所以无法直接覆盖返回地址？！

      ### 请分析
      1. 重新计算溢出偏移量，确认能否覆盖返回地址
      2. 如果200字节不足以覆盖返回地址，是否存在其他利用路径？
      3. 考虑栈溢出与栈布局的精确关系
      4. 能否通过第一关的返回值控制执行流？
      5. 分析是否能利用 validate_and_respond 函数的返回值来间接控制执行
      6. 给出完整的利用方案

  }

  // ===== 阶段2: 综合分析报告 =====

  (reverse_engineer, vulnerability_analyst, rop_chain_builder) -> report_writer

  agent report_writer {
    model: "gpt-4"
    permission allow: [read, glob, grep, write]
    system_prompt: "你是一名CTF pwn方向的报告撰写专家。请综合所有分析结果，生成一份完整的、结构清晰的二进制分析报告。"

    prompt: |
      请综合以下三个分析视角的结果，生成一份完整的 CTF pwn 二进制分析报告：

      1. **逆向工程视角**: 程序整体逻辑、各函数功能、执行流程
      2. **漏洞分析视角**: 安全漏洞识别、漏洞利用可行性、攻击面分析
      3. **ROP链构造视角**: 溢出偏移计算、gadget利用、完整的exploit方案

      报告需要包含：
      - 程序概要（架构、保护、功能）
      - 执行流程详细分析
      - 漏洞细节（如果有）
      - 漏洞利用方案（步骤）
      - 总结与建议

      请将报告保存到文件 E:\opencode-desktop\GrassFlow\pwn_analysis_report.md

      注意：分析要保持客观，明确指出分析中的不确定之处。
  }
}
