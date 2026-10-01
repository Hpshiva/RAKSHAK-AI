import os
import sqlite3
from datetime import datetime
from database import get_connection

def generate_html_summary_report():
    """Generates an HTML summary report of all detected incidents."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, label, confidence, severity, camera, count, detected_at FROM detections ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()

    total_logs = len(rows)
    critical_count = sum(1 for r in rows if r['severity'] == 'CRITICAL')
    high_count = sum(1 for r in rows if r['severity'] == 'HIGH')
    low_count = sum(1 for r in rows if r['severity'] == 'LOW')

    now_str = datetime.now().strftime("%B %d, %Y - %H:%M:%S")

    table_rows_html = ""
    for r in rows:
        sev_color = "#ef4444" if r['severity'] == 'CRITICAL' else ("#f97316" if r['severity'] == 'HIGH' else "#06b6d4")
        table_rows_html += f"""
        <tr>
            <td style="padding: 10px; border-bottom: 1px solid #334155;">{r['detected_at']}</td>
            <td style="padding: 10px; border-bottom: 1px solid #334155;"><strong>{r['label']}</strong></td>
            <td style="padding: 10px; border-bottom: 1px solid #334155;">{r['camera']}</td>
            <td style="padding: 10px; border-bottom: 1px solid #334155;">{r['confidence']:.1f}%</td>
            <td style="padding: 10px; border-bottom: 1px solid #334155; color: {sev_color}; font-weight: bold;">{r['severity']}</td>
            <td style="padding: 10px; border-bottom: 1px solid #334155;">{r['count']}</td>
        </tr>
        """

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Rakshak AI - Security Audit Report</title>
        <style>
            body {{ font-family: Arial, sans-serif; background-color: #0f172a; color: #f8fafc; margin: 0; padding: 40px; }}
            .header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #00d2ff; padding-bottom: 20px; margin-bottom: 30px; }}
            .title {{ font-size: 24px; font-weight: bold; color: #00d2ff; }}
            .stats-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin-bottom: 30px; }}
            .stat-card {{ background: #1e293b; padding: 15px; border-radius: 8px; border: 1px solid #334155; text-align: center; }}
            .stat-num {{ font-size: 22px; font-weight: bold; margin-top: 5px; }}
            table {{ width: 100%; border-collapse: collapse; background: #1e293b; border-radius: 8px; overflow: hidden; }}
            th {{ background: #0f172a; text-align: left; padding: 12px 10px; color: #94a3b8; font-size: 13px; text-transform: uppercase; }}
        </style>
    </head>
    <body>
        <div class="header">
            <div>
                <div class="title">🛡️ RAKSHAK AI SECURITY AUDIT REPORT</div>
                <div style="color: #94a3b8; font-size: 14px; margin-top: 5px;">Generated on {now_str}</div>
            </div>
        </div>

        <div class="stats-grid">
            <div class="stat-card">
                <div style="color: #94a3b8; font-size: 12px;">TOTAL INCIDENTS</div>
                <div class="stat-num">{total_logs}</div>
            </div>
            <div class="stat-card">
                <div style="color: #ef4444; font-size: 12px;">CRITICAL THREATS</div>
                <div class="stat-num" style="color: #ef4444;">{critical_count}</div>
            </div>
            <div class="stat-card">
                <div style="color: #f97316; font-size: 12px;">HIGH SEVERITY</div>
                <div class="stat-num" style="color: #f97316;">{high_count}</div>
            </div>
            <div class="stat-card">
                <div style="color: #06b6d4; font-size: 12px;">LOW SEVERITY</div>
                <div class="stat-num" style="color: #06b6d4;">{low_count}</div>
            </div>
        </div>

        <h3>Detailed Incident History</h3>
        <table>
            <thead>
                <tr>
                    <th>Timestamp</th>
                    <th>Classification</th>
                    <th>Camera</th>
                    <th>Confidence</th>
                    <th>Severity</th>
                    <th>Occurrences</th>
                </tr>
            </thead>
            <tbody>
                {table_rows_html if table_rows_html else "<tr><td colspan='6' style='padding:20px; text-align:center;'>No security alerts recorded.</td></tr>"}
            </tbody>
        </table>
    </body>
    </html>
    """
    return html_content
