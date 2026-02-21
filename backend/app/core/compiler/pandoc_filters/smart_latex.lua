--[[
  smart_latex.lua — Pandoc Lua filter for Smart-LaTeX Word export (Layer 3)

  Cleans up residual raw LaTeX that survives preprocessing:
    - RawInline: font commands, \fontsize, etc.
    - RawBlock:  \clearpage, \thispagestyle, \pagenumbering, \vfill, etc.
    - Header:    ensures level 4-6 headers get correct custom-style attributes
]]

-- ── RawInline handler ─────────────────────────────────────────────────────

function RawInline(el)
  if el.format ~= "latex" then return nil end
  local text = el.text

  -- \heiti{...} → Bold
  local heiti_content = text:match("\\heiti%s*{(.-)}")
  if heiti_content then
    return pandoc.Strong(pandoc.Str(heiti_content))
  end

  -- {\heiti ...} → Bold  (group-style)
  heiti_content = text:match("{\\heiti%s+(.-)}")
  if heiti_content then
    return pandoc.Strong(pandoc.Str(heiti_content))
  end

  -- \songti{...} or {\songti ...} → plain text
  local songti_content = text:match("\\songti%s*{(.-)}")
                      or text:match("{\\songti%s+(.-)}")
  if songti_content then
    return pandoc.Str(songti_content)
  end

  -- \fangsong{...} → plain text
  local fangsong_content = text:match("\\fangsong%s*{(.-)}")
                        or text:match("{\\fangsong%s+(.-)}")
  if fangsong_content then
    return pandoc.Str(fangsong_content)
  end

  -- \kaiti{...} → Emphasis
  local kaiti_content = text:match("\\kaiti%s*{(.-)}")
                     or text:match("{\\kaiti%s+(.-)}")
  if kaiti_content then
    return pandoc.Emph(pandoc.Str(kaiti_content))
  end

  -- Standalone font switches: \heiti, \songti, \fangsong, \kaiti → remove
  if text:match("^\\heiti%s*$")
    or text:match("^\\songti%s*$")
    or text:match("^\\fangsong%s*$")
    or text:match("^\\kaiti%s*$")
  then
    return pandoc.Str("")
  end

  -- \fontsize{...}{...}\selectfont → remove
  if text:match("\\fontsize%s*{.-}{.-}\\selectfont") then
    return pandoc.Str("")
  end

  -- \selectfont alone → remove
  if text:match("^\\selectfont%s*$") then
    return pandoc.Str("")
  end

  -- \bfseries → remove (Pandoc handles bold through \textbf)
  if text:match("^\\bfseries%s*$") then
    return pandoc.Str("")
  end

  -- \normalfont → remove
  if text:match("^\\normalfont%s*$") then
    return pandoc.Str("")
  end

  return nil  -- keep other raw inline as-is
end


-- ── RawBlock handler ──────────────────────────────────────────────────────

function RawBlock(el)
  if el.format ~= "latex" then return nil end
  local text = el.text

  -- \clearpage / \newpage → OpenXML page break
  if text:match("^%s*\\clearpage%s*$") or text:match("^%s*\\newpage%s*$") then
    local page_break = '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'
    return pandoc.RawBlock("openxml", page_break)
  end

  -- \thispagestyle{...} → remove
  if text:match("\\thispagestyle") then
    return pandoc.RawBlock("openxml", "")
  end

  -- \pagestyle{...} → remove
  if text:match("\\pagestyle") then
    return pandoc.RawBlock("openxml", "")
  end

  -- \pagenumbering{...} → remove
  if text:match("\\pagenumbering") then
    return pandoc.RawBlock("openxml", "")
  end

  -- \vfill → remove
  if text:match("^%s*\\vfill%s*$") then
    return pandoc.RawBlock("openxml", "")
  end

  -- \vspace{...} / \vspace*{...} → remove
  if text:match("\\vspace%*?%s*{.-}") then
    return pandoc.RawBlock("openxml", "")
  end

  -- \mainpagegeometry → remove
  if text:match("\\mainpagegeometry") then
    return pandoc.RawBlock("openxml", "")
  end

  -- \newgeometry{...} → remove
  if text:match("\\newgeometry") then
    return pandoc.RawBlock("openxml", "")
  end

  -- \begingroup / \endgroup → remove
  if text:match("^%s*\\begingroup%s*$") or text:match("^%s*\\endgroup%s*$") then
    return pandoc.RawBlock("openxml", "")
  end

  -- \setlength, \setcounter → remove
  if text:match("\\setlength") or text:match("\\setcounter") then
    return pandoc.RawBlock("openxml", "")
  end

  -- Font declarations in blocks → remove
  if text:match("\\setCJK") or text:match("\\setmainfont") or text:match("\\newCJKfontfamily") then
    return pandoc.RawBlock("openxml", "")
  end

  -- titleformat/titlespacing/titlecontents → remove
  if text:match("\\titleformat") or text:match("\\titlespacing") or text:match("\\titlecontents") then
    return pandoc.RawBlock("openxml", "")
  end

  -- fancyhdr commands → remove
  if text:match("\\fancyhf") or text:match("\\fancyhead") or text:match("\\fancyfoot") then
    return pandoc.RawBlock("openxml", "")
  end
  if text:match("\\renewcommand{\\headrulewidth}") or text:match("\\renewcommand{\\footrulewidth}") then
    return pandoc.RawBlock("openxml", "")
  end

  -- Empty or whitespace-only blocks → remove
  if text:match("^%s*$") then
    return pandoc.RawBlock("openxml", "")
  end

  return nil  -- keep other raw blocks
end


-- Note: Pandoc automatically maps header levels to Word Heading styles.
-- No custom Header handler needed — levels 1-6 are handled by default.
