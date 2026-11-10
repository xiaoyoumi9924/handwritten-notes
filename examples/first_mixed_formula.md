# 静态链与 Display 表

S 的当前静态层为 \(M(0), Q(1), R2(2), S(3)\)。 The active record starts at `sp`.

S 的局部 Display 表为：

\[
D_S[0] = sp_M, \quad D_S[1] = sp_Q, \quad D_S[2] = sp_{R2}, \quad D_S[3] = sp_S.
\]

地址计算：

\[
z: D_S[4] \text{ 不存在，不可访问}
\]


\[
x: sp_S + off_x = sp + off_x
\]

\[
y: D_S[2] + off_y = sp_{R2} + off_y
\]

静态链为 \(S \to R2 \to Q \to M\)，动态链为 \(S \to R2 \to R1 \to Q \to P \to M\)。

再检查一个矩阵公式：

\[
A = \begin{bmatrix} a_{11} & a_{12} \\ a_{21} & a_{22} \end{bmatrix}
\]
