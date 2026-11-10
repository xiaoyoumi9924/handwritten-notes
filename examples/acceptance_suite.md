# 中英混排与数学公式验收样稿

这份固定样稿用于比较每次渲染改动。正文以中文为主，穿插英文术语、变量名和 LaTeX；重点检查内容是否完整、基线是否协调、公式是否清晰，以及分页是否自然。

## 行内公式与中英混排

在编译器的 activation record 中，变量地址由当前层的活动记录起始地址和偏移量组成。若当前过程为 \(S\)，它的 frame pointer 是 \(sp_S\)，那么局部变量 \(x\) 的地址写作 \(sp_S+off_x\)。对于外层过程 \(R2\) 中的变量 \(y\)，需要沿 static link 找到 \(R2\)，再计算 \(sp_{R2}+off_y\)。

行内公式既可能出现在句首，也可能出现在解释中间或句尾：\(E=mc^2\) 描述能量关系；速度满足 \(v=\frac{s}{t}\)，因此经过时间 \(t\) 的位移为 \(d=vt\)。当 \(x_i^2+\sqrt{\frac{a+b}{c}}>0\) 时，继续检查下一步。English terms such as stack frame, lexical scope, and static link should remain readable beside Chinese text.

中文紧邻变量\(a+b\)和英文 identifier，逗号后的公式 \(x_1,x_2\) 也要保留标点间距。下面这段故意让行内公式接近行尾：根据测得的质量、速度、温度变化和材料参数，代入模型并完成单位换算与误差修正后，我们得到 \(E_k=\frac{1}{2}mv^2\)，然后再继续说明实验条件和结果。

For a constant speed \(v=\frac{s}{t}\), the traveled distance after time \(t\) is \(d=vt\). This sentence places an inline formula near the line edge: after substituting the measured values and simplifying the expression, we obtain \(x=\frac{-b+\sqrt{b^2-4ac}}{2a}\), which should stay together as one readable formula.

## 独立公式与数学结构

Display 表中每一项记录当前活动记录的起始地址：

\[
D_S[0]=sp_M,\quad D_S[1]=sp_Q,\quad D_S[2]=sp_{R2},\quad D_S[3]=sp_S.
\]

对于抽象地址 \((2,off_y)\)，当前 Display 表给出的实际地址为 \(D_S[2]+off_y=sp_{R2}+off_y\)。变量 \(z\) 若位于不存在的 level 4，则在当前静态作用域中不可访问。

分数、根式和上下标需要保持结构清楚：

\[
x_{1,2}=\frac{-b\pm\sqrt{b^2-4ac}}{2a},\qquad
R=\frac{1}{1+\frac{1}{1+\frac{1}{x}}}.
\]

求和与积分也会出现在中文解释之后：

\[
\sum_{i=1}^{n} i=\frac{n(n+1)}{2},\qquad
\int_{0}^{1}x^2\,dx=\frac{1}{3}.
\]

矩阵的行列和括号应对齐，分段函数的条件应留在对应分支旁边：

\[
A=\begin{bmatrix}1 & x_1 & x_1^2\\1 & x_2 & x_2^2\\1 & x_3 & x_3^2\end{bmatrix},\qquad
f(x)=\begin{cases}x^2,&x\ge0\\-x,&x<0\end{cases}.
\]

## 多行推导与换行边界

下面的等式组检查多行公式的对齐关系；中文说明、英文 connector 和公式需要保持在同一份手写稿中协调呈现。

\[
\begin{aligned}
(x+1)^2 &= x^2+2x+1 \\
        &= (x-1)^2+4x \\
        &= x^2-2x+1+4x.
\end{aligned}
\]

行内长句和块级长公式都不能被页面边界截断。若推导过长，应在语义完整的位置分行，等号列保持整齐：

\[
\begin{aligned}
\frac{x^2-1}{x-1}
  &= \frac{(x-1)(x+1)}{x-1} \\
  &= x+1,\qquad x\ne1.
\end{aligned}
\]

同一页还要容纳普通段落：公式规则优先保证正确和可读，正文笔迹保持轻微自然变化。请留意标题是否孤行、公式是否靠近页边、最后一段是否被分页切断，以及英文字符的倾斜是否稳定。
