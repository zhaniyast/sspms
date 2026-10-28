# North University Student Portal — UI/UX Prototype

Responsive, English-language student-facing portal prototype.

## Included
- Home overview, profile and settings tabs
- Weekly timetable and today's schedule
- Courses, Calendar (Month/Week/List), Grades, Performance, Attendance
- Performance risk gauge, illustrative grade estimate, factors, interactive What-if sliders
- AI Assistant page and floating chat widget
- Messages, feedback surveys and placeholder study planner / transcript / documents / support
- Mobile bottom navigation, light/dark theme preview and KZ/RU/EN selector
- Demo-only sample data and interactions

## Run
No package installation is required. Extract the ZIP and open `index.html` in Chrome or Edge.

Recommended local server on Windows:
```powershell
py -m http.server 8000
```
Then open http://127.0.0.1:8000/

macOS/Linux:
```bash
python3 -m http.server 8000
```

## Files
- `index.html`: screen structure
- `styles.css`: responsive design and components
- `app.js`: sample data, navigation and interactions

## Limitations
This is a static UI/UX prototype, not a production application. All names, grades, attendance, deadlines, risk indicators and AI responses are illustrative. Forms and actions run only in the browser and do not persist to a server. Language selection is a preview; full translations are not yet implemented. Chart.js and Google Fonts load from CDNs. Do not enter real student information.
