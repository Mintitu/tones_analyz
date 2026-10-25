# -------------------------------------------------------------
    # 1. RAPORT TABELAR COMPACT HTML & MARKDOWN (Analiza.md)
    # -------------------------------------------------------------
    tbl_md = f"# 📊 Analiză Detaliată Portofoliu XTB\n\n"
    tbl_md += f"**Data generării:** `{current_time}`  \n"
    tbl_md += f"**Randament Total Portofoliu:** `{sign}{total_gain_pct:.2f}%`  \n"
    tbl_md += f"**Valoare Totală / Cost:** `${total_value:,.2f}` / `${total_cost:,.2f}`  \n\n"
    tbl_md += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    # Început container cu font micșorat (85% din mărimea standard)
    tbl_md += f"<div style='font-size: 85%; font-family: monospace;'>\n\n"
    tbl_md += f"| Ticker | Preț | TP | ATH | P&L | Evaluare & Semnal | RSI | P/E | FP/E | P/B | EV/EBITDA | ROA | ROE | ROIC | Profit M. | Div Yld | Payout | EPS Y | EPS Y+1 |\n"
    tbl_md += f"|:---|:---:|:---:|:---:|:---:|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|\n"

    for r in rows:
        p_pct = r['gain_pct']
        p_sign = "+" if p_pct >= 0 else ""
        price_str = f"{r['cur_price']:.2f}$" if r['cur_price'] is not None else "N/A"
        tp_str = f"{r['target_price']:.1f}$" if r['target_price'] is not None else "-"
        gap_str = f"{r['gap']:.0f}%" if r['gap'] is not None else "-"
        ev_str = f"{r['ev_ebitda']:.1f}x" if r['ev_ebitda'] is not None else "-"
        
        roic_val = r['roic'] * 100 if r['roic'] is not None else None
        roic_str = f"{roic_val:.1f}%" if roic_val is not None else "-"
        
        roa_val = r['roa'] * 100 if r['roa'] is not None else None
        roa_str = f"{roa_val:.1f}%" if roa_val is not None else "-"
        
        roe_val = r['roe'] * 100 if r['roe'] is not None else None
        roe_str = f"{roe_val:.1f}%" if roe_val is not None else "-"
        
        pm_val = r['profit_margins'] * 100 if r['profit_margins'] is not None else None
        pm_str = f"{pm_val:.1f}%" if pm_val is not None else "-"
        
        div_val = r['div_yield'] * 100 if r['div_yield'] is not None else None
        div_str = f"{div_val:.2f}%" if div_val is not None else "-"
        
        payout_val = r['payout_ratio'] * 100 if r['payout_ratio'] is not None else None
        payout_str = f"{payout_val:.1f}%" if payout_val is not None else "-"

        eps_this_val = r['eps_this_y'] * 100 if r['eps_this_y'] is not None else None
        eps_this_str = f"{eps_this_val:.1f}%" if eps_this_val is not None else "-"

        eps_next_val = r['eps_next_y'] * 100 if r['eps_next_y'] is not None else None
        eps_next_str = f"{eps_next_val:.1f}%" if eps_next_val is not None else "-"
        
        pb_str = f"{r['price_to_book']:.2f}" if r['price_to_book'] is not None else "-"
        rsi_str = f"{r['rsi']:.0f}" if r['rsi'] is not None else "-"
        pe_val = r['trailing_pe']
        pe_str = f"{pe_val:.1f}" if pe_val is not None else "-"
        fwd_pe_str = f"{r['forward_pe']:.1f}" if r['forward_pe'] is not None else "-"

        eval_signal_cell = f"{r['bullet']} **{r['score']}** {r['reason']}"
        
        tbl_md += f"| **{r['symbol']}** | {price_str} | {tp_str} | {gap_str} | `{p_sign}{p_pct:.1f}%` | {eval_signal_cell} | {rsi_str} | {pe_str} | {fwd_pe_str} | {pb_str} | {ev_str} | {roa_str} | {roe_str} | {roic_str} | {pm_str} | {div_str} | {payout_str} | {eps_this_str} | {eps_next_str} |\n"

    tbl_md += f"\n</div>\n"
