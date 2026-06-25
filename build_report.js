/**
 * VenCap Report Builder
 * Generates branded Word documents matching the Board Paper Template.
 *
 * Usage:
 *   node build_report.js '<json_payload>' <output_path>
 *
 * JSON payload shape:
 * {
 *   "title": "VenCap 16 — Q1 2025 Performance Summary",
 *   "month": "May",
 *   "year": "2025",
 *   "date": "May 2025",
 *   "template": "board_paper",   // "board_paper" | "letterhead"
 *   "executive_summary": "Short paragraph summarising the paper.",
 *   "sections": [
 *     {
 *       "heading": "Capital Calls",
 *       "format": "prose",          // "prose" | "bullets" | "table"
 *       "content": "Narrative text goes here.",
 *       "bullets": ["Point one", "Point two"],
 *       "table": {
 *         "headers": ["Fund", "Amount", "Date"],
 *         "rows": [["VenCap 16", "$1,000,000", "Q1 2025"]]
 *       }
 *     }
 *   ]
 * }
 */

const fs = require("fs");
const path = require("path");

const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, ImageRun, AlignmentType, HeadingLevel, BorderStyle,
  WidthType, ShadingType, VerticalAlign, PageNumber, PageBreak,
  LevelFormat, Tab, TabStopType, TabStopPosition,
} = require("docx");

// ── Brand tokens (from Board Paper Template XML analysis) ─────────────────────
const BRAND = {
  fontName:       "Proxima Nova",
  bgPage:         "F2EBE7",   // warm off-white page background
  blueDark:       "144380",   // section titles, borders, primary header bar
  blueLight:      "1F57A4",   // alternate header/footer bar
  greyBold:       "565A5C",   // bold body text
  greyNormal:     "8B8D8E",   // normal body text
  white:          "FFFFFF",
  red:            "FF0000",   // "PRIVILEGED AND CONFIDENTIAL"
  tableHeaderBg:  "144380",   // table header fill = blueDark
  tableHeaderFg:  "FFFFFF",
  tableAltBg:     "E8EEF6",   // light blue alternating row
  bodySize:       20,         // 10pt in half-points
  titleSize:      28,         // 14pt in half-points
  confidSize:     20,
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function run(text, opts = {}) {
  return new TextRun({
    text,
    font:      opts.font  ?? BRAND.fontName,
    size:      opts.size  ?? BRAND.bodySize,
    bold:      opts.bold  ?? false,
    color:     opts.color ?? BRAND.greyNormal,
    allCaps:   opts.caps  ?? false,
  });
}

function sectionTitle(text) {
  return new Paragraph({
    spacing: { before: 200, after: 100 },
    children: [
      new TextRun({
        text,
        font:  BRAND.fontName,
        size:  BRAND.titleSize,
        bold:  true,
        color: BRAND.blueDark,
      }),
    ],
  });
}

function bodyParagraph(boldText, normalText) {
  const children = [];
  if (boldText) {
    children.push(new TextRun({
      text: boldText + (normalText ? " " : ""),
      font: BRAND.fontName, size: BRAND.bodySize,
      bold: true, color: BRAND.greyBold,
    }));
  }
  if (normalText) {
    children.push(new TextRun({
      text: normalText,
      font: BRAND.fontName, size: BRAND.bodySize,
      bold: false, color: BRAND.greyNormal,
    }));
  }
  return new Paragraph({ spacing: { after: 80 }, children });
}

function emptyLine() {
  return new Paragraph({
    children: [new TextRun({ text: "", font: BRAND.fontName, size: BRAND.bodySize })],
  });
}

// ── Bullet list ───────────────────────────────────────────────────────────────
function bulletParagraph(text) {
  return new Paragraph({
    numbering: { reference: "bullets", level: 0 },
    spacing: { after: 60 },
    children: [
      new TextRun({ text, font: BRAND.fontName, size: BRAND.bodySize, color: BRAND.greyNormal }),
    ],
  });
}

// ── Data table ────────────────────────────────────────────────────────────────
function dataTable(headers, rows) {
  const colCount  = headers.length;
  const tableW    = 9026;  // A4 with 1" margins
  const colW      = Math.floor(tableW / colCount);
  const lastColW  = tableW - colW * (colCount - 1);
  const colWidths = headers.map((_, i) => (i === colCount - 1 ? lastColW : colW));

  const border = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
  const borders = { top: border, bottom: border, left: border, right: border };

  const headerRow = new TableRow({
    tableHeader: true,
    children: headers.map((h, i) =>
      new TableCell({
        borders,
        width: { size: colWidths[i], type: WidthType.DXA },
        shading: { fill: BRAND.tableHeaderBg, type: ShadingType.CLEAR },
        margins: { top: 80, bottom: 80, left: 120, right: 120 },
        children: [new Paragraph({
          children: [new TextRun({
            text: h, font: BRAND.fontName, size: BRAND.bodySize,
            bold: true, color: BRAND.tableHeaderFg,
          })],
        })],
      })
    ),
  });

  const dataRows = rows.map((row, ri) =>
    new TableRow({
      children: row.map((cell, ci) =>
        new TableCell({
          borders,
          width: { size: colWidths[ci], type: WidthType.DXA },
          shading: {
            fill: ri % 2 === 1 ? BRAND.tableAltBg : "FFFFFF",
            type: ShadingType.CLEAR,
          },
          margins: { top: 80, bottom: 80, left: 120, right: 120 },
          children: [new Paragraph({
            children: [new TextRun({
              text: String(cell ?? ""),
              font: BRAND.fontName, size: BRAND.bodySize,
              color: BRAND.greyNormal,
            })],
          })],
        })
      ),
    })
  );

  return new Table({
    width: { size: tableW, type: WidthType.DXA },
    columnWidths: colWidths,
    rows: [headerRow, ...dataRows],
  });
}

// ── Executive summary box ─────────────────────────────────────────────────────
function execSummaryBox(titleText, summaryText) {
  const border = { style: BorderStyle.SINGLE, size: 4, color: BRAND.blueDark };
  const borders = { top: border, bottom: border, left: border, right: border };

  return new Table({
    width: { size: 9026, type: WidthType.DXA },
    columnWidths: [9026],
    rows: [
      new TableRow({
        children: [
          new TableCell({
            borders,
            width: { size: 9026, type: WidthType.DXA },
            shading: { fill: BRAND.bgPage, type: ShadingType.CLEAR },
            margins: { top: 120, bottom: 120, left: 180, right: 180 },
            children: [
              new Paragraph({
                children: [new TextRun({
                  text: titleText,
                  font: BRAND.fontName, size: BRAND.titleSize,
                  bold: true, color: BRAND.blueDark,
                })],
              }),
              emptyLine(),
              new Paragraph({
                children: [new TextRun({
                  text: summaryText,
                  font: BRAND.fontName, size: BRAND.bodySize,
                  bold: true, color: BRAND.greyBold,
                })],
              }),
            ],
          }),
        ],
      }),
    ],
  });
}

// ── Header ────────────────────────────────────────────────────────────────────
function buildHeader(titleText, monthYear) {
  // Line 1: "PRIVILEGED AND CONFIDENTIAL" right-aligned in red
  const confidLine = new Paragraph({
    alignment: AlignmentType.RIGHT,
    spacing: { after: 0 },
    children: [new TextRun({
      text: "PRIVILEGED AND CONFIDENTIAL",
      font: BRAND.fontName, size: BRAND.confidSize,
      color: BRAND.red,
    })],
  });

  // Blue bar with title — implemented as a table (full-width, single cell)
  const titleBar = new Table({
    width: { size: 9026, type: WidthType.DXA },
    columnWidths: [9026],
    rows: [
      new TableRow({
        children: [
          new TableCell({
            borders: {
              top:    { style: BorderStyle.NONE },
              bottom: { style: BorderStyle.NONE },
              left:   { style: BorderStyle.NONE },
              right:  { style: BorderStyle.NONE },
            },
            width: { size: 9026, type: WidthType.DXA },
            shading: { fill: BRAND.blueDark, type: ShadingType.CLEAR },
            margins: { top: 85, bottom: 85, left: 0, right: 0 },
            verticalAlign: VerticalAlign.CENTER,
            children: [
              new Paragraph({
                alignment: AlignmentType.CENTER,
                children: [new TextRun({
                  text: `${titleText}  ${monthYear}`.trim(),
                  font: BRAND.fontName, size: BRAND.titleSize,
                  bold: true, color: BRAND.white,
                })],
              }),
            ],
          }),
        ],
      }),
    ],
  });

  return new Header({ children: [confidLine, titleBar, emptyLine()] });
}

// ── Footer ────────────────────────────────────────────────────────────────────
function buildFooter(logoImageData, dateText) {
  // Blue bar footer: date left | page number centre
  // Tab stop at centre (4513 twips ≈ halfway across A4)
  // NOTE: Tab must be inside its own TextRun to be schema-valid
  const footerChildren = [
    new Paragraph({
      shading: { fill: BRAND.blueDark, type: ShadingType.CLEAR },
      tabStops: [
        { type: TabStopType.CENTER, position: 4513 },
      ],
      children: [
        new TextRun({
          text: dateText,
          font: BRAND.fontName, size: 18,
          allCaps: true, color: BRAND.white,
        }),
        // Tab wrapped in its own run (schema requirement)
        new TextRun({ children: [new Tab()] }),
        new TextRun({
          children: [PageNumber.CURRENT],
          font: BRAND.fontName, size: BRAND.bodySize,
          allCaps: true, color: BRAND.white,
        }),
      ],
    }),
  ];

  return new Footer({ children: footerChildren });
}

// ── Section renderer ──────────────────────────────────────────────────────────
function renderSection(section) {
  const elements = [];

  elements.push(sectionTitle(section.heading));

  switch (section.format) {
    case "bullets":
      if (section.content) {
        elements.push(bodyParagraph(null, section.content));
      }
      (section.bullets || []).forEach(b => elements.push(bulletParagraph(b)));
      break;

    case "table":
      if (section.content) {
        elements.push(bodyParagraph(null, section.content));
        elements.push(emptyLine());
      }
      if (section.table) {
        elements.push(dataTable(section.table.headers, section.table.rows));
      }
      break;

    case "prose":
    default: {
      const lines = (section.content || "").split("\n").filter(Boolean);
      lines.forEach(line => elements.push(bodyParagraph(null, line)));
      break;
    }
  }

  elements.push(emptyLine());
  return elements;
}


// ── PowerPoint generation via pptxgenjs ──────────────────────────────────────
async function buildPPTX(payload, outputPath, logoData) {
  const PptxGenJS = require("pptxgenjs");
  const pptx = new PptxGenJS();

  const title   = payload.title   || "VenCap Report";
  const date    = payload.date    || "";
  const slides  = payload.slides  || [];

  // Brand tokens matching the VenCap master template
  const NAVY   = "144380";
  const CREAM  = "F2EBE7";
  const GREY   = "83888D";
  const GREYBOLD = "565A5C";
  const WHITE  = "FFFFFF";
  const logoB64 = logoData ? logoData.toString("base64") : null;

  // Slide size: 10.83" x 7.5" (widescreen, matching master template)
  pptx.defineLayout({ name: "VENCAP", width: 10.83, height: 7.5 });
  pptx.layout = "VENCAP";

  function addLogo(slide) {
    if (!logoB64) return;
    slide.addImage({ data: `image/png;base64,${logoB64}`, x: 9.4, y: 0.1, w: 1.2, h: 0.45, sizing: { type: "contain", w: 1.2, h: 0.45 } });
  }

  function addFooter(slide, pageDate) {
    slide.addText("vencap.com", { x: 0.3, y: 7.15, w: 2, h: 0.2, fontSize: 7, color: GREY, fontFace: "Proxima Nova" });
    if (pageDate) {
      slide.addText(pageDate, { x: 4, y: 7.15, w: 3, h: 0.2, fontSize: 7, color: GREY, fontFace: "Proxima Nova", align: "center" });
    }
  }

  slides.forEach((slide, idx) => {
    const s = pptx.addSlide();
    s.background = { color: CREAM };

    switch (slide.layout) {

      case "title_slide":
        s.addText(slide.title || title, {
          x: 0.9, y: 2.5, w: 8.5, h: 1.2,
          fontSize: 35, bold: true, color: NAVY, fontFace: "Proxima Nova Black", wrap: true
        });
        if (slide.subtitle) s.addText(slide.subtitle, {
          x: 0.9, y: 3.8, w: 8.5, h: 0.6,
          fontSize: 28, color: GREY, fontFace: "Proxima Nova", wrap: true
        });
        if (slide.date || date) s.addText(slide.date || date, {
          x: 0.9, y: 4.5, w: 8.5, h: 0.5,
          fontSize: 24, bold: true, color: NAVY, fontFace: "Proxima Nova Bold"
        });
        // Bottom bar
        s.addShape(pptx.ShapeType.rect, { x: 2.5, y: 7.0, w: 5.75, h: 0.25, fill: { color: CREAM } });
        addLogo(s);
        addFooter(s, slide.date || date);
        break;

      case "section_break":
        s.addText(slide.title || "", {
          x: 1.7, y: 2.8, w: 7.44, h: 0.9,
          fontSize: 30, bold: true, color: NAVY, fontFace: "Proxima Nova Black",
          align: "center", wrap: true
        });
        addLogo(s);
        addFooter(s, date);
        break;

      case "bullets": {
        s.addText(slide.title || "", {
          x: 0.65, y: 0.6, w: 9.5, h: 0.6,
          fontSize: 30, bold: true, color: NAVY, fontFace: "Proxima Nova Black"
        });
        const bullets = (slide.bullets || []).map(b => ({
          text: b, options: { bullet: true, fontSize: 16, color: GREYBOLD, fontFace: "Proxima Nova", paraSpaceAfter: 4 }
        }));
        if (bullets.length) {
          s.addText(bullets, { x: 0.65, y: 1.4, w: 9.5, h: 5.2, valign: "top", wrap: true });
        }
        addLogo(s);
        addFooter(s, date);
        break;
      }

      case "table": {
        s.addText(slide.title || "", {
          x: 0.65, y: 0.6, w: 9.5, h: 0.6,
          fontSize: 30, bold: true, color: NAVY, fontFace: "Proxima Nova Black"
        });
        if (slide.subtitle) s.addText(slide.subtitle, {
          x: 0.65, y: 1.25, w: 9.5, h: 0.3,
          fontSize: 16, color: GREY, fontFace: "Proxima Nova"
        });
        if (slide.table) {
          const tableY = slide.subtitle ? 1.65 : 1.4;
          const headers = (slide.table.headers || []).map(h => ({
            text: h, options: { bold: true, color: WHITE, fill: { color: NAVY }, fontSize: 12, fontFace: "Proxima Nova Bold" }
          }));
          const rows = (slide.table.rows || []).map((row, ri) =>
            row.map(cell => ({
              text: String(cell ?? ""),
              options: { fontSize: 11, color: GREYBOLD, fontFace: "Proxima Nova",
                fill: { color: ri % 2 === 1 ? "E8EEF6" : WHITE } }
            }))
          );
          s.addTable([headers, ...rows], {
            x: 0.65, y: tableY, w: 9.5,
            border: { type: "solid", color: "CCCCCC", pt: 0.5 },
            rowH: 0.28
          });
        }
        addLogo(s);
        addFooter(s, date);
        break;
      }

      case "content":
      default:
        s.addText(slide.title || "", {
          x: 0.65, y: 0.6, w: 9.5, h: 0.6,
          fontSize: 30, bold: true, color: NAVY, fontFace: "Proxima Nova Black"
        });
        if (slide.body) s.addText(slide.body, {
          x: 0.65, y: 1.4, w: 9.5, h: 5.5,
          fontSize: 16, color: GREY, fontFace: "Proxima Nova", wrap: true, valign: "top"
        });
        addLogo(s);
        addFooter(s, date);
        break;
    }
  });

  await pptx.writeFile({ fileName: outputPath });
}

// ── Main ──────────────────────────────────────────────────────────────────────
async function main() {
  const payload    = JSON.parse(process.argv[2]);
  const outputPath = process.argv[3] || "report.docx";
  const isPPTX     = outputPath.toLowerCase().endsWith(".pptx");

  const logoData = fs.readFileSync(path.join(__dirname, "Logo.png"));

  if (isPPTX) {
    // ── PowerPoint path ────────────────────────────────────────────────────
    await buildPPTX(payload, outputPath, logoData);
    console.log(`Written: ${outputPath}`);
    return;
  }

  // ── Word path (unchanged) ─────────────────────────────────────────────────
  const title     = payload.title     || "VenCap Report";
  const month     = payload.month     || "";
  const year      = payload.year      || "";
  const dateText  = payload.date      || `${month} ${year}`.trim();
  const monthYear = `${month} ${year}`.trim();
  const execSum   = payload.executive_summary || "";
  const sections  = payload.sections  || [];

  const bodyChildren = [];

  if (execSum) {
    bodyChildren.push(execSummaryBox("Executive Summary", execSum));
    bodyChildren.push(emptyLine());
  }

  sections.forEach(s => {
    renderSection(s).forEach(el => bodyChildren.push(el));
  });

  const doc = new Document({
    numbering: {
      config: [{
        reference: "bullets",
        levels: [{
          level: 0,
          format: LevelFormat.BULLET,
          text: "•",
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } },
        }],
      }],
    },
    background: { color: BRAND.bgPage },
    sections: [{
      properties: {
        page: {
          size:   { width: 11906, height: 16838 },
          margin: { top: 1200, right: 1000, bottom: 1200, left: 1000 },
        },
      },
      headers: { default: buildHeader(title, monthYear) },
      footers: { default: buildFooter(logoData, dateText) },
      children: bodyChildren,
    }],
  });

  const buffer = await Packer.toBuffer(doc);
  fs.writeFileSync(outputPath, buffer);
  await injectFooterLogo(outputPath, logoData);
  console.log(`Written: ${outputPath}`);
}

/**
 * Inject the VenCap logo into the generated document's footer.
 * Works by directly manipulating the ZIP (docx) contents.
 */
async function injectFooterLogo(docxPath, logoData) {
  const AdmZip = (() => {
    try { return require("adm-zip"); } catch { return null; }
  })();

  if (!AdmZip) {
    // Fallback: use Python's zipfile via child_process
    await injectFooterLogoPython(docxPath, logoData);
    return;
  }

  const zip = new AdmZip(docxPath);
  _injectIntoZip(zip, logoData);
  zip.writeZip(docxPath);
}

async function injectFooterLogoPython(docxPath, logoData) {
  const { execFileSync } = require("child_process");
  const tmpLogo = docxPath + ".logo.png";
  fs.writeFileSync(tmpLogo, logoData);

  const scriptPath = path.join(__dirname, "inject_logo.py");
  try {
    execFileSync("python", [scriptPath, docxPath, tmpLogo], { stdio: "pipe" });
  } finally {
    if (fs.existsSync(tmpLogo)) fs.unlinkSync(tmpLogo);
  }
}
// close file
main().catch(e => { console.error(e); process.exit(1); });