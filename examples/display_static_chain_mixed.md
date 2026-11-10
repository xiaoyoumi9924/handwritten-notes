# Display 表与静态链地址解析

This note checks Chinese explanations, English compiler terms, inline math, and display equations in the same page.

## 1. 当前调用层级与 Display 表

当前调用链的静态层级为 M(0)、Q(1)、R2(2)、S(3)。S 的 lexical parent 是 R2；虽然 P 和 Q 位于同一静态层，S 的 lexical scope 仍沿 S→R2→Q→M 查找。

S 的局部 Display 表记录每一层当前活动记录（activation record）的起始地址：

\[
D_S[0]=sp_M,\quad D_S[1]=sp_Q,\quad D_S[2]=sp_{R2},\quad D_S[3]=sp_S
\]

对于抽象地址 \((3,off_x)\)，x 位于当前 S 层，因此实际地址是 \(sp_S+off_x\)。对于 \((2,off_y)\)，y 位于 R2 层，实际地址是 \(D_S[2]+off_y=sp_{R2}+off_y\)。

如果 z 的抽象地址是 \((4,off_z)\)，当前最大静态层为 3，Display 中没有 \(D_S[4]\)，所以 z 在当前作用域不可访问。

<newpage>

## 2. Dynamic link 与 static link

Dynamic chain follows the caller sequence S→R2→R1→Q→P→M. Static links follow lexical parents: S→R2, R2→Q, R1→Q, Q→M, and P→M.

要解析 y，运行时从 S 的 static link 到达 R2，再将 offset 加到 R2 的 activation record 起始地址。R2 的 dynamic predecessor 是 R1，但 R1 不是 S 的 lexical parent；dynamic link 和 static link 不能混用。

两种方法最终定位到同一变量地址：\(D_S[2]+off_y=sp_{R2}+off_y\)。英文标识符、中文解释和公式应在同一行自然衔接；长公式靠近行尾时应作为完整 expression 换到下一行。
