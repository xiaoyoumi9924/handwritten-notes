# 行内公式与中英正文混排

本样张用于检查行内公式与正文的基线、间距、标点、自动折行和两端对齐。

## 公式出现在句首、句中和句尾

句首公式 \(E=mc^2\) 后继续中文说明；句中变量 \(m\) 表示质量，\(c\) 表示光速；句尾保留完整公式 \(Q=cm\Delta T\)。

English: For a constant speed \(v=\frac{s}{t}\), the traveled distance after time \(t\) is \(d=vt\). The formula should sit naturally on the text baseline.

## 上下标和根式混排行文

当 \(x_i^2+\sqrt{\frac{a+b}{c}}\) 大于某个阈值时，继续检查下一个条件。For \(x_i^2+\sqrt{\frac{a+b}{c}}>0\), the expression remains inline and should not disturb the surrounding words.

中文紧邻公式\(a+b\)并接着中文；English text immediately before \(a_i^2\) and immediately after it should remain readable.

## 靠近行尾的公式与自动换行

这段中文故意写得较长，让公式接近行尾：根据前面测得的质量、速度和时间数据代入模型，经过单位换算与误差修正后，得到 \(E_k=\frac{1}{2}mv^2\)，再继续解释计算结果和实验条件。

This English sentence is also intentionally long so the inline expression approaches the right edge of a line before continuing: after substituting the measured values, the result is \(x=\frac{-b+\sqrt{b^2-4ac}}{2a}\), which should move as a complete formula if the line runs out of space.

## 标点和相邻公式

中文括号内的公式（\(a^2+b^2=c^2\)），以及逗号后的公式 \(x_1,x_2\) 应保持标点位置自然。

Multiple short expressions: \(a+b\), \(c-d\), and \(e\times f\) appear in one English sentence without unnatural gaps.
