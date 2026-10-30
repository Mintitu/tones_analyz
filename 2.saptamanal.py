# Citirea conținutului din analiza.md pentru a adăuga contextul săptămânal
    rezumat_md = "Context indisponibil: analiza.md nu a fost găsit."
    for name in ["analiza.md", "docs/analiza.md"]:
        ap = ROOT / name
        if ap.exists():
            rezumat_md = ap.read_text(encoding="utf-8")
            break

    # Construirea mesajului final structurat pentru Telegram / Markdown
    lines = [
        "# 📊 RAPORT SĂPTĂMÂNAL PORTOFOLIU XTB",
        f"Săptămână încheiată la {anchor}; ședințe {week[0].date()} - {end.date()}.",
        f"Valoare totală portofoliu: **{positions['Value'].sum():,.2f} USD**.",
        f"Poziții cu date valide: {available}/{len(rows)}.",
        "",
        "## ⚖️ Semnale & Rebalansare 50/50",
        "- Sistemul analizează dinamica activelor pe ultimele 5 zile lucrătoare (Luni-Vineri) corelat cu densitatea portofoliului.",
        "",
        "## 📈 Sinteză din Analiza Săptămânală (Luni - Vineri):"
    ]
    
    # Adăugăm liniile relevante din analiza.md (primele 20 de rânduri sau sinteza)
    linii_md = [l for l in rezumat_md.split('\n') if l.strip()][:20]
    lines.extend(linii_md)
    
    # Salvăm în fișierul Markdown final care va fi trimis și pe Telegram
    report = OUT / "weekly_report.md"
    report.write_text("\n".join(lines), encoding="utf-8")