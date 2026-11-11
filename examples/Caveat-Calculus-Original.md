### The Strict Calculus Proof

1.  Equation of the circle: \(r^2 + u^2 = 1\).
2.  Take the derivative with respect to \(u\):
    \[
 2r \frac{dr}{du} + 2u = 0 \implies \frac{dr}{du} = -\frac{u}{r} 
\]
    *(Note: \(-\frac{u}{r}\) is essentially the reciprocal of the slope/tangent, which relates to \(\tan\theta\))*.
3.  The formula for arc length in terms of \(u\) is:
    \[
 dl = \sqrt{1 + \left(\frac{dr}{du}\right)^2} \, du 
\]
4.  Substitute \(\frac{dr}{du}\):
    \[
 dl = \sqrt{1 + \left(-\frac{u}{r}\right)^2} \, du = \sqrt{1 + \frac{u^2}{r^2}} \, du 
\]
5.  Get a common denominator inside the square root:
    \[
 dl = \sqrt{\frac{r^2 + u^2}{r^2}} \, du 
\]
6.  Since \(r^2 + u^2 = 1\):
    \[
 dl = \sqrt{\frac{1}{r^2}} \, du = \frac{1}{r} \, du 
\]
7.  Since \(r = \sqrt{1-u^2}\):
    \[
 dl = \frac{du}{\sqrt{1-u^2}} 
\]
