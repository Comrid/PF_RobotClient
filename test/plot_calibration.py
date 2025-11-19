import matplotlib.pyplot as plt
import numpy as np

# Calibration data
SPEEDS = [30,   40,   50,   60,   70,   80,   90,  100]
RATIOS = [0.88, 0.84, 0.8, 0.76, 0.72, 0.66, 0.60, 0.58]

# Create plot
plt.figure(figsize=(10, 6))
plt.plot(SPEEDS, RATIOS, 'o-', linewidth=2, markersize=8, color='blue', label='Calibration Ratio')

# Linear regression from 30 to 100
x_start, y_start = SPEEDS[0], RATIOS[0]  # (30, 0.85)
x_end, y_end = SPEEDS[-1], RATIOS[-1]     # (100, 0.6)

# Calculate linear regression: y = ax + b
slope = (y_end - y_start) / (x_end - x_start)
intercept = y_start - slope * x_start

# Generate line points
x_line = np.array([x_start, x_end])
y_line = slope * x_line + intercept

# Plot linear regression line
plt.plot(x_line, y_line, 'r--', linewidth=2, label=f'Linear Fit (30-100): y = {slope:.4f}x + {intercept:.4f}')

# 2nd degree polynomial regression using all data points
x_data = np.array(SPEEDS)
y_data = np.array(RATIOS)
coeffs = np.polyfit(x_data, y_data, 2)  # 2차 다항식 계수 [a, b, c] where y = ax^2 + bx + c

# Generate smooth curve for polynomial
x_poly = np.linspace(x_start, x_end, 100)
y_poly = np.polyval(coeffs, x_poly)

# Plot 2nd degree polynomial regression
plt.plot(x_poly, y_poly, 'g--', linewidth=2, 
         label=f'Quadratic Fit (all points): y = {coeffs[0]:.6f}x² + {coeffs[1]:.4f}x + {coeffs[2]:.4f}')

# Format plot
plt.xlabel('Speed', fontsize=12)
plt.ylabel('Ratio', fontsize=12)
plt.title('Motor Calibration: Speed vs Ratio', fontsize=14, fontweight='bold')
plt.grid(True, alpha=0.3)
plt.legend()

# Annotate each point
for speed, ratio in zip(SPEEDS, RATIOS):
    plt.annotate(f'{ratio:.2f}', (speed, ratio), 
                textcoords="offset points", xytext=(0,10), ha='center', fontsize=9)

# Adjust Y-axis range
plt.ylim(0.5, 0.9)

# Display plot
plt.tight_layout()
plt.show()

