---
name: TwinForge Industrial Operations
colors:
  surface: '#f8f9ff'
  surface-dim: '#cbdbf5'
  surface-bright: '#f8f9ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#eff4ff'
  surface-container: '#e5eeff'
  surface-container-high: '#dce9ff'
  surface-container-highest: '#d3e4fe'
  on-surface: '#0b1c30'
  on-surface-variant: '#3f4850'
  inverse-surface: '#213145'
  inverse-on-surface: '#eaf1ff'
  outline: '#707881'
  outline-variant: '#bfc7d2'
  surface-tint: '#006398'
  primary: '#006194'
  on-primary: '#ffffff'
  primary-container: '#007bb9'
  on-primary-container: '#fdfcff'
  inverse-primary: '#93ccff'
  secondary: '#5b5e68'
  on-secondary: '#ffffff'
  secondary-container: '#dcdfeb'
  on-secondary-container: '#5f626c'
  tertiary: '#006b2c'
  on-tertiary: '#ffffff'
  tertiary-container: '#00873a'
  on-tertiary-container: '#f7fff2'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#cce5ff'
  primary-fixed-dim: '#93ccff'
  on-primary-fixed: '#001d31'
  on-primary-fixed-variant: '#004b73'
  secondary-fixed: '#dfe2ed'
  secondary-fixed-dim: '#c3c6d1'
  on-secondary-fixed: '#181c24'
  on-secondary-fixed-variant: '#434750'
  tertiary-fixed: '#7ffc97'
  tertiary-fixed-dim: '#62df7d'
  on-tertiary-fixed: '#002109'
  on-tertiary-fixed-variant: '#005320'
  background: '#f8f9ff'
  on-background: '#0b1c30'
  surface-variant: '#d3e4fe'
typography:
  headline-xl:
    fontFamily: IBM Plex Sans
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: IBM Plex Sans
    fontSize: 18px
    fontWeight: '600'
    lineHeight: 24px
    letterSpacing: -0.015em
  headline-sm:
    fontFamily: IBM Plex Sans
    fontSize: 14px
    fontWeight: '600'
    lineHeight: 20px
    letterSpacing: -0.01em
  body-md:
    fontFamily: IBM Plex Sans
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px
  body-sm:
    fontFamily: IBM Plex Sans
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 16px
  data-lg:
    fontFamily: JetBrains Mono
    fontSize: 18px
    fontWeight: '600'
    lineHeight: 22px
    letterSpacing: -0.02em
  data-md:
    fontFamily: JetBrains Mono
    fontSize: 13px
    fontWeight: '500'
    lineHeight: 16px
    letterSpacing: -0.01em
  data-sm:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: '400'
    lineHeight: 14px
  label-caps:
    fontFamily: JetBrains Mono
    fontSize: 10px
    fontWeight: '600'
    lineHeight: 12px
    letterSpacing: 0.06em
  label-compact:
    fontFamily: IBM Plex Sans
    fontSize: 11px
    fontWeight: '500'
    lineHeight: 14px
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  gutter: 0.75rem
  gutter-compact: 0.5rem
  margin: 1rem
  margin-dock: 0.5rem
  space-xs: 0.25rem
  space-sm: 0.375rem
  space-md: 0.5rem
  space-lg: 0.75rem
  space-xl: 1rem
---

## Brand & Style

This design system serves technical operators, plant reliability engineers, and manufacturing automation directors navigating complex, real-time industrial telemetry. The brand aesthetic merges industrial precision engineering with high-density data visualization.

### Aesthetic Principles
- **Mission-Critical Precision:** Every pixel, edge, and label signals reliability and zero ambiguity. Visuals evoke high-performance SCADA consoles, precision calibration apparatus, and CAD/BIM operational environments.
- **High-Density Utility:** Maximize actionable telemetry per square inch without visual clutter. Prioritize data legibility, rapid scanning, and rapid incident isolation over decorative negative space.
- **Engineered Contrast:** Dual-mode architecture pairing an ultra-dark graphite navigation chrome (`#0F1218` / `#181C24`) for situational permanence with a calibrated light engineering canvas (`#F8FAFC` / `#F3F5F7`) for long-shift analytical legibility.
- **Architectural Rigor:** Governed by structural 1px grid borders, hairline dividers, and monospaced alignment of numerical parameters.

## Colors

The system uses a calibrated dual-tier industrial chromatic system engineered for operational clarity and zero-latency status comprehension.

### Core Canvas & Structural Chrome
- **Workspace Canvas:** Light technical gray (`#F8FAFC` base, `#F1F5F9` recessed surfaces, `#FFFFFF` elevated instrument tiles).
- **Control Chrome / Sidebar:** Deep graphite (`#0F1218` background, `#181C24` card/dock background, `#2A303C` border dividers).
- **Structural Dividers:** Hairline slate borders (`#E2E8F0` primary surface borders, `#CBD5E1` emphasized structural thresholds).

### Interactive Accent
- **Precision Blue (`#0284C7` primary, `#0369A1` interactive hover, `#075985` active/pressed, `#E0F2FE` soft selection surface):** Exclusively reserved for primary system actions, focused telemetry cursors, active navigation tabs, and multi-axis plot selectors.

### Telemetry Status Tokens
- **Operational / Normal:** `#16A34A` (Indicator fill), `#15803D` (Label text), `#DCFCE7` (Micro-badge surface).
- **Warning / Degraded / Thermal Drift:** `#D97706` (Indicator fill), `#B45309` (Label text), `#FEF3C7` (Micro-badge surface).
- **Critical / Fault / Offline:** `#DC2626` (Indicator fill), `#B91C1C` (Label text), `#FEE2E2` (Micro-badge surface).
- **Dormant / Disconnected / Uncalibrated:** `#64748B` (Indicator fill), `#334155` (Label text), `#F1F5F9` (Micro-badge surface).

## Typography

The typographical pairing distinguishes human-authored metadata from deterministic machine telemetry.

### Font Roles
- **IBM Plex Sans:** Drives hierarchical headings, tabular textual records, navigation links, and administrative parameters. It delivers industrial neutrality and distinct character open counters.
- **JetBrains Mono:** Dedicated exclusively to machine IDs, UUIDs, sensor telemetry outputs, timestamps (ISO-8601), SCADA coordinates, raw math formulas, and micro status chips. Numbers render in tabular/tabular-slashed form with zero variable-width jitter.

### Rules of Engagement
- All data cells showing rates (kW/h, RPM, PSI, °C) must render in `JetBrains Mono`.
- Sub-labels and category trackers utilize `label-caps` in uppercase format with wide tracking (`0.06em`) for immediate peripheral vision parsing across field monitors.

## Layout & Spacing

A compact, multi-pane docking philosophy prioritizes functional scan rates and split-second operational intervention.

### Grid & Viewport Model
- **Fixed Multi-Pane Dashboard Architecture:** Primary shell features a fixed 240px or collapsed 56px charcoal operational rail, an optional secondary asset tree panel (280px), and a fluid multi-viewport telemetry canvas.
- **Data Densification:** Standard component gaps and paddings stay within `0.25rem` (`space-xs`) to `0.75rem` (`space-lg`). Large padding blocks (> `1.5rem`) are prohibited inside production monitoring areas.
- **Viewport Layout:** 12-column layout utilizing `0.75rem` gutters. Elements reflow via responsive grid anchors, maintaining minimum readable instrument sizes (min-width: 320px for multi-axis chart cards, min-width: 160px for scalar KPI blocks).

## Elevation & Depth

Visual hierarchy uses crisp boundary delineation and flat structural layering rather than heavy ambient drop shadows.

### Elevation Strategy
- **Layer 0 (Canvas Base):** `#F1F5F9` / `#F8FAFC` flat structural plane.
- **Layer 1 (Telemetry Panels & Instrument Cards):** Pure white `#FFFFFF` surface bounded by a razor-sharp 1px border (`#E2E8F0`). Zero ambient blur; depth is established entirely through boundary contrast.
- **Layer 2 (Overlays & Calibrators):** Inspector drawers, flyout menus, and quick-calibrate dialogs receive a sharp, low-diffuse technical shadow: `0 1px 3px 0 rgba(15, 23, 42, 0.08), 0 1px 2px -1px rgba(15, 23, 42, 0.08)`, combined with a 1px `#CBD5E1` border.
- **Layer 3 (Modal Alerts & Emergency Diagnostics):** Deep backdrop overlay (`rgba(15, 18, 24, 0.75)`) with crisp containment card bounded by 1px `#475569`.

## Shapes

The interface implements a restrained corner radius (`0.25rem` / `4px`) reflecting machined industrial hardware tooling.

### Corner Radius Standards
- **Instrument Tiles & Control Surfaces:** `0.25rem` (4px). Provides subtle softening without sacrificing the structural grid alignment characteristic of physical instrument racks.
- **Micro-Badges & Telemetry Indicators:** `0.125rem` (2px) or strictly squared (`0px`) for high-density tabular markers.
- **Buttons, Selectors & Input Frames:** `0.25rem` (4px). Pill shapes (`rounded-full`) are prohibited except for pulsing live sensor status beacons (dots).

## Components

### Buttons & Operational Triggers
- **Primary Action (Precision Blue):** Height `32px` (compact), background `#0284C7`, text `#FFFFFF`, border `1px solid #0369A1`. Hover: `#0369A1`. Focus: `2px solid #38BDF8` with `1px` white offset.
- **Secondary / Calibration Button:** Height `32px`, background `#FFFFFF`, text `#334155`, border `1px solid #CBD5E1`. Hover: `#F8FAFC`, border `#94A3B8`.
- **Destructive / Emergency Cutoff:** Height `32px`, background `#DC2626`, text `#FFFFFF`, border `1px solid #B91C1C`.

### Telemetry Micro-Badges & Status Chips
- **Dimensions:** Max height `20px`, padding `0 6px`, font `JetBrains Mono` at `10px` or `11px` weight `600`.
- **Live Indicator Dot:** `6px` circular beacon placed before text. Pulsing animation allowed solely on `Fault` (`#DC2626`) or `Degraded` (`#D97706`) states.
- **Construction:** Inset border `1px` matched to 20% opacity of the status token; solid tinted background at 10% opacity.

### Telemetry Sparklines & Data Visualizers
- **Background:** Framed inside `#FFFFFF` cards with hairline 1px `#E2E8F0` separators.
- **Line Width:** 1.5px vector strokes in `#0284C7` (primary metric), `#64748B` (nominal baseline), or semantic status colors for threshold infringements.
- **Grid Lines:** Hairline dashed `#E2E8F0` on light mode; crosshair coordinates snap using monospaced tooltips with zero entry delay.

### High-Density Data Tables
- **Header:** Height `28px`, background `#F8FAFC`, border-bottom `1px solid #CBD5E1`, text uppercase `JetBrains Mono` 10px `#64748B`.
- **Rows:** Alternating subtle zebra striping (`#FFFFFF` to `#FBFCFD`), height `32px`, border-bottom `1px solid #F1F5F9`.
- **Alignment:** Alphanumeric IDs and numerical values are right-aligned in `JetBrains Mono`; labels and entity types are left-aligned in `IBM Plex Sans`.

### Input Controls & Setpoint Adjusters
- **Text/Numeric Inputs:** Height `30px`, font `JetBrains Mono` 12px, border `1px solid #CBD5E1`, background `#FFFFFF`. Active focus: border `1px solid #0284C7` with box-shadow `0 0 0 1px #0284C7`.
- **Checkbox & Radio Elements:** `14px x 14px` square profile with 2px radius. Check fill `#0284C7`, border `#94A3B8`.