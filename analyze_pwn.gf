workflow analyze_pwn {
  // Agent 1: 分析函数列表和入口点
  agent function_analysis {
    model: "gpt-4o"
    prompt: |-
      你是一个二进制分析专家。请基于以下 GDB 信息分析 pwn 二进制文件的可执行函数结构。

      ## 入口点和函数地址
      入口点: 0x80490f0
      函数信息:
      ┌──────────────────────────────────────────────────────────────┐
      0x80490f0  entry0
      0x8049040  _init
      0x80491e0  _start
      0x8049210  _dl_relocate_static_pie
      0x80492a0  deregister_tm_clones
      0x80492e0  register_tm_clones
      0x8049320  __do_global_dtors_aux
      0x8049370  frame_dummy
      0x8049409  main
      0x8049372  vuln
      0x80493b4  win
      0x80493f2  gadget
      0x8049460  __libc_csu_init
      0x80494d0  __libc_csu_fini
      0x80494d4  _fini
      ┌──────────────────────────────────────────────────────────────┐

      请分析:
      1. 这个文件有哪些关键函数（main, vuln, win, gadget）？
      2. 从函数命名推断这个程序是做什么的（CTF pwn 挑战）
      3. 列出函数调用关系和程序结构

    output: result
    permission allow: [read]
  }

  // Agent 2: 分析 vuln 函数反汇编（漏洞函数）
  agent vuln_analysis {
    model: "gpt-4o"
    prompt: |-
      你是一个二进制漏洞分析专家。请分析以下 vuln 函数的反汇编代码。

      ## vuln 函数 (@0x8049372)
      ```
      0x8049372  push   ebp
      0x8049373  mov    ebp, esp
      0x8049375  sub    esp, 0x28          ; 分配 40 字节栈空间
      0x8049378  sub    esp, 0xc
      0x804937b  push   0x8049540          ; "system" 字符串的地址
      0x8049380  call   0x80492a0          ; 调用 puts/printf 打印提示
      0x8049385  add    esp, 0x10
      0x8049388  sub    esp, 0xc
      0x804938b  lea    eax, [ebp-0x28]    ; 缓冲区地址 = ebp-0x28 (40字节)
      0x804938e  push   eax
      0x804938f  call   0x80492e0          ; 调用 gets/read -> 缓冲区溢出!
      0x8049394  add    esp, 0x10
      0x8049397  nop
      0x8049398  leave
      0x8049399  ret
      ```

      请分析:
      1. 这个函数存在什么漏洞？
      2. 缓冲区大小和栈布局（ebp-0x28 = 40字节缓冲区，返回地址在 ebp+4）
      3. 如何利用这个漏洞？
      4. 距离覆盖返回地址需要多少字节？

    output: result
    permission allow: [read]
  }

  // Agent 3: 分析 win 函数（后门函数）
  agent win_analysis {
    model: "gpt-4o"
    prompt: |-
      你是一个二进制漏洞分析专家。请分析以下 win 函数的反汇编代码。

      ## win 函数 (@0x80493b4) — 后门函数
      ```
      0x80493b4  push   ebp
      0x80493b5  mov    ebp, esp
      0x80493b7  sub    esp, 0x18
      0x80493ba  sub    esp, 0xc
      0x80493bd  push   0x804954c          ; "/bin/sh" 字符串地址
      0x80493c2  call   0x80492e0          ; 可能是 system()
      0x80493c7  add    esp, 0x10
      0x80493ca  sub    esp, 0xc
      0x80493cd  push   0x8049554          ; 另一个字符串
      0x80493d2  call   0x80492e0          ; 又一个调用
      0x80493d7  add    esp, 0x10
      0x80493da  nop
      0x80493db  leave
      0x80493dc  ret
      ```

      ## gadget 函数 (@0x80493f2)
      ```
      0x80493f2  pop    ebx
      0x80493f3  ret
      ```

      请分析:
      1. win 函数的功能是什么？（执行 /bin/sh）
      2. 为什么这是一个"后门"函数？
      3. gadget 函数提供了什么有用的 ROP 小工具？
      4. 完整的利用思路是什么？

    output: result
    permission allow: [read]
  }

  // Agent 4: 综合分析 + 生成利用方案
  agent exploit_plan {
    model: "gpt-4o"
    prompt: |-
      你是一个 CTF pwn 漏洞利用专家。请综合所有分析结果，给出完整的利用方案。

      ## 已知信息汇总

      ### 保护机制
      - NX enabled
      - 无 PIE (固定基址)
      - 32位 i386 ELF

      ### 关键地址
      - vuln 函数: 0x8049372
      - win 函数: 0x80493b4 (后门)
      - gadget (pop ebx; ret): 0x80493f2
      - /bin/sh 字符串: 0x804954c

      ### 漏洞
      - vuln 中使用了 gets() 读取到 40 字节缓冲区 (ebp-0x28)
      - 返回地址位于 ebp+4
      - 栈布局: [buffer(40)] + [saved_ebp(4)] + [ret_addr(4)]
      - 覆盖偏移量: 40 + 4 = 44 字节后覆盖返回地址

      ### 利用思路
      - 由于 NX 开启，无法直接在栈上执行 shellcode
      - 有现成的 win() 后门函数 (0x80493b4) 可以调用，执行 system("/bin/sh")
      - 直接 ret2win: padding(44) + win_addr(0x80493b4)
      - 也可以考虑 ret2libc 或 ROP

      请给出:
      1. 完整的利用方案（选最优方法）
      2. Python exploit 代码（使用 pwntools）
      3. 分步骤解释利用过程

    output: result
    permission allow: [read]
  }

  // 所有 Agent 并行执行
  (function_analysis, vuln_analysis, win_analysis) -> exploit_plan
}
