const $=id=>document.getElementById(id);
const courses=[
{name:"Database Systems",code:"DBS 302",teacher:"Dr. Elena Kim",credits:3,progress:68,grade:"B+",score:84,color:"#5e7be5",mark:"DB",tone:"blue",next:"Assignment 4 · Oct 29",assessments:[["Quiz 1","10%","17/20","Sep 15"],["Assignment 2","20%","82/100","Oct 02"],["Quiz 2","10%","18/20","Oct 21"],["Assignment 3","20%","72/100","Oct 23"],["Assignment 4","20%","Due Oct 29","Upcoming"]]},
{name:"Modern Regression",code:"SDS 301",teacher:"Dr. Elena Kim",credits:3,progress:74,grade:"A−",score:89,color:"#34b67f",mark:"MR",tone:"green",next:"Regression report · Nov 05",assessments:[["Problem Set 1","15%","91/100","Sep 12"],["Midterm","25%","86/100","Oct 03"],["Lab Report","20%","90/100","Oct 17"],["Regression report","20%","Upcoming","Nov 05"]]},
{name:"Machine Learning",code:"CSS 324",teacher:"Prof. Daniel Lee",credits:4,progress:62,grade:"B+",score:85,color:"#e4a13a",mark:"ML",tone:"amber",next:"Model evaluation quiz · Nov 02",assessments:[["Quiz 1","10%","16/20","Sep 10"],["Mini Project","20%","84/100","Oct 01"],["Quiz 2","10%","18/20","Oct 21"],["Model evaluation quiz","15%","Upcoming","Nov 02"]]},
{name:"Statistical Learning",code:"SDS 405",teacher:"Dr. Mira Patel",credits:3,progress:80,grade:"A",score:92,color:"#9879e4",mark:"SL",tone:"violet",next:"Reading response · Nov 03",assessments:[["Reading response","10%","95/100","Sep 22"],["Midterm","25%","90/100","Oct 09"],["Lab exercise","15%","91/100","Oct 20"]]},
{name:"Data Ethics",code:"SDS 407",teacher:"Dr. Samir Khan",credits:2,progress:86,grade:"A−",score:90,color:"#e1799c",mark:"DE",tone:"rose",next:"Case reflection · Nov 06",assessments:[["Case study","20%","92/100","Oct 01"],["Midterm reflection","20%","88/100","Oct 16"]]},
{name:"Research Methods",code:"RES 301",teacher:"Dr. Aigerim Sadyk",credits:3,progress:55,grade:"B",score:81,color:"#51a8bd",mark:"RM",tone:"teal",next:"Research outline · Nov 09",assessments:[["Proposal","20%","82/100","Oct 10"],["Research outline","25%","Upcoming","Nov 09"]]}
];
const events=[
{day:27,month:10,course:"Modern Regression",type:"Class",title:"Modern Regression · Lecture",time:"10:00–11:30",tone:"green"},
{day:27,month:10,course:"Machine Learning",type:"Class",title:"Machine Learning · Lab",time:"12:30–14:00",tone:"amber"},
{day:29,month:10,course:"Database Systems",type:"Assignment",title:"Assignment 4 due",time:"23:59",tone:"blue",deadline:true},
{day:30,month:10,course:"Statistical Learning",type:"Class",title:"Statistical Learning · Practice",time:"12:30–14:00",tone:"violet"},
{day:2,month:11,course:"Machine Learning",type:"Quiz",title:"Model evaluation quiz",time:"11:00",tone:"amber"},
{day:5,month:11,course:"Modern Regression",type:"Assignment",title:"Regression report due",time:"23:59",tone:"green",deadline:true},
{day:6,month:11,course:"Data Ethics",type:"Assignment",title:"Case reflection",time:"23:59",tone:"rose",deadline:true},
{day:9,month:11,course:"Research Methods",type:"Assignment",title:"Research outline",time:"23:59",tone:"teal",deadline:true},
{day:12,month:11,course:"Database Systems",type:"Quiz",title:"SQL optimization quiz",time:"14:00",tone:"blue"}
];
const attendance=[
["Oct 27","Modern Regression","Lecture · C105","Present","present"],["Oct 27","Machine Learning","Lab · Lab 3","Present","present"],["Oct 26","Database Systems","Lecture · B204","Present","present"],["Oct 23","Statistical Learning","Practice · A312","Late","late"],["Oct 22","Machine Learning","Lecture · Lab 3","Present","present"],["Oct 21","Database Systems","Practice · B204","Absent","absent"],["Oct 20","Modern Regression","Lecture · C105","Present","present"],["Oct 19","Statistical Learning","Lecture · A312","Excused","excused"]
];
let calendarMonth=10,calendarYear=2026,calendarView="Month",toastTimer,target=90,currentContact="Dr. Elena Kim";
function toast(msg){const t=$("toast");t.textContent=msg;t.classList.add("show");clearTimeout(toastTimer);toastTimer=setTimeout(()=>t.classList.remove("show"),2700)}
function esc(v){return String(v).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]))}
function showPage(page){document.querySelectorAll(".page").forEach(p=>p.classList.toggle("active",p.id==="page-"+page));document.querySelectorAll(".nav[data-page],.mobile-nav [data-page]").forEach(b=>b.classList.toggle("active",b.dataset.page===page));const names={home:"Home",courses:"Courses",calendar:"Calendar",grades:"Grades",performance:"Performance",attendance:"Attendance",assistant:"AI Assistant",messages:"Messages",feedback:"Feedback",planner:"Study Planner",transcript:"Transcript",documents:"Documents",support:"Support & Library"};$("crumb").textContent=names[page]||page;$("sidebar").classList.remove("mobile-open");window.scrollTo({top:0,behavior:"smooth"});if(page==="performance")initCharts();if(page==="calendar")renderCalendar()}
function card(c){return `<article class="course-card" style="--color:${c.color}" data-course="${esc(c.name)}"><div class="course-top"><span class="course-mark mark-${c.tone}">${c.mark}</span><div><h3>${esc(c.name)}</h3><small class="course-code">${c.code}</small></div><small class="course-credits">${c.credits} cr</small></div><p class="course-teacher">${esc(c.teacher)}</p><div class="course-progress"><span>Course progress</span><b>${c.progress}%</b></div><div class="thin-progress"><i style="width:${c.progress}%"></i></div><div class="course-foot"><span>Next: ${esc(c.next)}</span><b>${c.grade}</b></div></article>`}
function renderCourses(){$("homeCourses").innerHTML=courses.slice(0,4).map(card).join("");$("allCourses").innerHTML=courses.map(card).join("")}
function modal(title,html,confirm="Got it",callback=null){$("modalTitle").textContent=title;$("modalBody").innerHTML=html;$("modalBackdrop").hidden=false;$("modalConfirm").textContent=confirm;$("modalConfirm").onclick=()=>{if(callback)callback();$("modalBackdrop").hidden=true}}
function tone(t){return ({blue:["#5e7be5","#eaf0ff","#4058b9"],green:["#34b67f","#e6f8ef","#16875a"],amber:["#e4a13a","#fff3df","#a96c13"],violet:["#9879e4","#f1ecff","#7652bb"],rose:["#e1799c","#fff0f5","#b64c70"],teal:["#51a8bd","#e8f7fa","#2a7f91"]})[t]||["#6177e8","#edf0ff","#4058b9"]}
function renderCalendar(){
 $("calendarTitle").textContent=new Date(calendarYear,calendarMonth-1,1).toLocaleDateString("en-US",{month:"long",year:"numeric"});
 $("miniMonthTitle").textContent=$("calendarTitle").textContent;
 const cfilters=[...document.querySelectorAll("[data-course]")].filter(x=>x.checked).map(x=>x.dataset.course);
 const tfilters=[...document.querySelectorAll("[data-type]")].filter(x=>x.checked).map(x=>x.dataset.type);
 const filtered=events.filter(e=>cfilters.includes(e.course)&&tfilters.includes(e.type));
 const canvas=$("calendarCanvas");
 if(calendarView==="List"){canvas.innerHTML=filtered.filter(e=>e.month===calendarMonth).map(e=>`<button class="list-event" data-event="${esc(e.title)}|${esc(e.time+" · "+e.course)}"><strong>${e.day} ${new Date(calendarYear,e.month-1,e.day).toLocaleDateString("en-US",{month:"short"})}</strong><span>${esc(e.title)}<small>${esc(e.time+" · "+e.course)}</small></span></button>`).join("")||"<p>No events match your filters.</p>";return}
 const names=["MON","TUE","WED","THU","FRI","SAT","SUN"];
 if(calendarView==="Week"){let html=names.map(n=>`<div class="weekday">${n}</div>`).join("");for(let i=0;i<7;i++){let day=26+i;let es=filtered.filter(e=>e.day===day&&e.month===10);html+=`<div class="month-day ${day===27?"today":""}"><span class="num">${day}</span>${es.map(e=>`<button class="event-chip" style="--ec:${tone(e.tone)[0]};--eb:${tone(e.tone)[1]};--et:${tone(e.tone)[2]}" data-event="${esc(e.title)}|${esc(e.time+" · "+e.course)}">${esc(e.title)}</button>`).join("")}</div>`}canvas.innerHTML=`<div class="month-grid">${html}</div>`;return}
 const first=new Date(calendarYear,calendarMonth-1,1),count=new Date(calendarYear,calendarMonth,0).getDate(),start=(first.getDay()+6)%7,prevCount=new Date(calendarYear,calendarMonth-1,0).getDate();let html=names.map(n=>`<div class="weekday">${n}</div>`).join("");
 for(let i=0;i<42;i++){let day,month=calendarMonth,out=false,year=calendarYear;if(i<start){day=prevCount-start+i+1;out=true;month=calendarMonth===1?12:calendarMonth-1;year=calendarMonth===1?calendarYear-1:calendarYear}else if(i>=start+count){day=i-start-count+1;out=true;month=calendarMonth===12?1:calendarMonth+1;year=calendarMonth===12?calendarYear+1:calendarYear}else day=i-start+1;
 const ev=filtered.filter(e=>e.day===day&&e.month===month).slice(0,2);
 html+=`<div class="month-day ${out?"outside":""} ${!out&&day===27&&calendarMonth===10?"today":""}"><span class="num">${day}</span>${ev.map(e=>`<button class="event-chip ${e.deadline?"deadline":""}" style="--ec:${tone(e.tone)[0]};--eb:${tone(e.tone)[1]};--et:${tone(e.tone)[2]}" data-event="${esc(e.title)}|${esc(e.time+" · "+e.course)}">${esc(e.title)}</button>`).join("")}</div>`}
 canvas.innerHTML=`<div class="month-grid">${html}</div>`;
 const mini=$("miniCalendar");let mh=names.map(n=>`<span>${n.slice(0,1)}</span>`).join("");for(let d=1;d<=new Date(calendarYear,calendarMonth,0).getDate();d++)mh+=`<button class="${d===27&&calendarMonth===10?"selected":""}" data-mini-day="${d}">${d}</button>`;mini.innerHTML=mh;
}
function renderGrades(){$("gradeList").innerHTML=courses.map((c,i)=>`<article class="grade-course ${i===0?"open":""}"><div class="grade-course-head"><span class="course-mark mark-${c.tone}">${c.mark}</span><span class="grade-name"><b>${c.name}</b><small>${c.code} · ${c.credits} credits</small></span><span class="grade-score"><b>${c.score}/100</b><small>Current score</small></span><span class="letter">${c.grade}</span><span class="expand">${i===0?"⌃":"⌄"}</span></div><div class="grade-details"><div class="assess-row head"><span>ASSESSMENT</span><span>WEIGHT</span><span>SCORE</span><span>DATE</span></div>${c.assessments.map(a=>`<div class="assess-row"><span>${a[0]} ${a[0]==="Quiz 2"?'<span style="color:#5366dc">● New</span>':""}</span><span>${a[1]}</span><span>${a[2]}</span><span>${a[3]}</span></div>`).join("")}</div></article>`).join("");document.querySelectorAll(".grade-course-head").forEach(h=>h.addEventListener("click",()=>{let c=h.closest(".grade-course");c.classList.toggle("open");h.querySelector(".expand").textContent=c.classList.contains("open")?"⌃":"⌄"}))}
function renderAttendance(){$("attendanceCards").innerHTML=[["Database Systems",84,"DBS 302"],["Modern Regression",94,"SDS 301"],["Machine Learning",90,"CSS 324"],["Statistical Learning",96,"SDS 405"]].map(a=>`<article class="panel att-card"><div class="ring" style="--ring:${a[1]<85?"#e4a13a":"#22ad78"};--value:${a[1]*3.6}deg"><b>${a[1]}%</b></div><div class="att-info"><b>${a[0]}</b><small>${a[2]}</small><em class="${a[1]<85?"warn":""}">${a[1]<85?"Near limit":"On track"}</em></div></article>`).join("");$("attendanceLog").innerHTML=`<div class="att-row head"><span>DATE</span><span>COURSE / CLASS</span><span>STATUS</span><span>DETAILS</span></div>`+attendance.map(a=>`<div class="att-row"><span>${a[0]}</span><span><b>${a[1]}</b><br><small>${a[2]}</small></span><span><b class="att-status ${a[4]}">${a[3]}</b></span><span>${a[3]==="Absent"?'<button class="text-btn" data-upload="1">Upload note</button>':"—"}</span></div>`).join("")}
function initCharts(){
 if(!window.Chart||$("riskChart").dataset.ready)return;
 Chart.defaults.font.family="'DM Sans',sans-serif";
 Chart.defaults.font.size=9;
 Chart.defaults.color="#8d97aa";
 new Chart($("riskChart"),{
  type:"line",
  data:{
   labels:["W2","W3","W4","W5","W6","W7","W8","W9"],
   datasets:[{
    label:"Risk",data:[34,38,45,62,55,42,33,28],
    borderColor:"#5366dc",backgroundColor:"rgba(83,102,220,.1)",
    fill:true,tension:.35,pointRadius:3,
    pointBackgroundColor:["#22ad78","#22ad78","#e5a13a","#d9525a","#e5a13a","#e5a13a","#22ad78","#22ad78"],
    borderWidth:2
   }]
  },
  options:{
   responsive:true,maintainAspectRatio:false,
   plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>`Illustrative risk: ${c.raw}%`}}},
   scales:{
    x:{grid:{display:false},border:{display:false}},
    y:{min:0,max:100,ticks:{callback:v=>v+"%"},grid:{color:"#eff1f6"},border:{display:false}}
   }
  }
 });
 new Chart($("activityChart"),{
  type:"line",
  data:{
   labels:["W2","W3","W4","W5","W6","W7","W8","W9"],
   datasets:[
    {label:"My activity",data:[3,4,5,3,4,6,5,5],borderColor:"#5366dc",tension:.35,borderWidth:2,pointRadius:2},
    {label:"Course average",data:[4,4,4,5,5,5,5,6],borderColor:"#b4bdcc",borderDash:[4,4],tension:.35,borderWidth:2,pointRadius:2}
   ]
  },
  options:{
   responsive:true,maintainAspectRatio:false,
   plugins:{legend:{display:false}},
   scales:{
    x:{grid:{display:false},border:{display:false}},
    y:{beginAtZero:true,max:10,ticks:{callback:v=>v+"h"},grid:{color:"#eff1f6"},border:{display:false}}
   }
  }
 });
 $("riskChart").dataset.ready="1";
}
function updateSimulator(){let s=+$("scoreSlider").value,h=+$("hoursSlider").value,o=+$("ontimeSlider").value;$("scoreValue").textContent=s;$("hoursValue").textContent=h;$("ontimeValue").textContent=o;let risk=Math.max(5,Math.min(85,Math.round(28+(80-s)*.22+(5-h)*1.6+(80-o)*.18)));let pts=Math.round(81+(s-80)*.09+(h-5)*.65+(o-80)*.06);let low=Math.max(50,Math.min(98,pts-4)),high=Math.max(low+2,Math.min(100,pts+4));let grade=pts>=90?"A−":pts>=85?"B+":pts>=80?"B":pts>=75?"B−":pts>=70?"C+":pts>=60?"C":"D";$("simRisk").textContent=risk+"%";$("riskChange").textContent=risk<28?`↓ ${28-risk} points from current`:risk>28?`↑ ${risk-28} points from current`:"Same as current estimate";$("simGrade").textContent=grade;$("simPoints").textContent=`${low}–${high} points`;$("simInsight").textContent=risk<20?"In this illustrative scenario, consistent study activity and timely submissions improve the estimate.":risk<35?"Your scenario is close to the current estimate. Small, consistent steps may help.":"This scenario increases the illustrative risk estimate. Consider a realistic study plan and ask your instructor for support.";$("gaugeArc").setAttribute("stroke",risk<30?"#22ad78":risk<55?"#e5a13a":"#d9525a");$("gaugeArc").setAttribute("d",risk<30?"M25 108 A85 85 0 0 1 129 27":risk<55?"M25 108 A85 85 0 0 1 155 33":"M25 108 A85 85 0 0 1 192 80");$("riskPercent").textContent=risk+"%";$("riskStatus").textContent=risk<30?"LOW RISK":risk<55?"MEDIUM RISK":"HIGHER RISK";$("riskStatus").className="risk-pill "+(risk<30?"low":risk<55?"medium":"high");$("forecastGrade").textContent=grade;$("forecastRange").textContent=`${low}–${high}`}
function reply(text){let t=text.toLowerCase();if(t.includes("deadline")||t.includes("due"))return"Your nearest sample deadline is Database Systems Assignment 4 on October 29. The Model Evaluation Quiz follows on November 2. Check your official course page for confirmed dates.";if(t.includes("class")||t.includes("today")||t.includes("schedule"))return"Your sample Tuesday schedule shows Modern Regression at 10:00 in C105, followed by Machine Learning Lab at 12:30 in Lab 3. Please confirm times with your official timetable.";if(t.includes("grade")||t.includes("improve")||t.includes("performance"))return"Start by finishing upcoming work on time, reviewing recent quiz mistakes, and scheduling short study blocks for difficult topics. These are general suggestions; use official grades and ask your instructor for course-specific advice.";if(t.includes("plan")||t.includes("study"))return"Try this sample plan: 30 minutes to outline Assignment 4, a short break, 25 minutes reviewing Quiz 2 mistakes, then a study block for Modern Regression topic 5. Adjust it to your real workload.";return"I can help you think through deadlines, study plans, grades and course topics. This prototype uses sample information and is not connected to a real AI service or university systems."}
function assistantMessage(text){let box=$("chatMessages");box.insertAdjacentHTML("beforeend",`<div class="bubble sent">${esc(text)}<small>Just now · Read</small></div><div class="bubble received">${esc(reply(text))}<small>Just now · Demo assistant</small></div>`);box.scrollTop=box.scrollHeight}
function downloadCSV(){let rows=[["Course","Code","Credits","Score","Grade"],...courses.map(c=>[c.name,c.code,c.credits,c.score,c.grade])];let blob=new Blob([rows.map(r=>r.map(x=>`"${String(x).replace(/"/g,'""')}"`).join(",")).join("\r\n")],{type:"text/csv;charset=utf-8"});let url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download="aidana-sample-grades.csv";a.click();URL.revokeObjectURL(url);toast("Sample grades CSV exported")}
function setLang(lang){$("langButton").textContent=lang+"⌄";$("langMenu").classList.remove("open");toast(lang==="EN"?"Interface language: English":lang==="RU"?"Russian translation will be added in a future version.":"Қазақша аударма келесі нұсқада қосылады.")}
function showModalEvent(title,detail){modal(title,`<div class="modal-body">${esc(detail)}</div>`,"Close")}
document.addEventListener("click",e=>{
 const page=e.target.closest("[data-page]");if(page){showPage(page.dataset.page);return}
 const event=e.target.closest("[data-event]");if(event){let [title,detail]=event.dataset.event.split("|");showModalEvent(title,detail);return}
 const prompt=e.target.closest("[data-prompt]");if(prompt){let txt=prompt.dataset.prompt;if(prompt.closest("#aiWidget")){$("aiWidget").classList.add("open");$("widgetBody").insertAdjacentHTML("beforeend",`<p><b>You:</b> ${esc(txt)}</p><p><b>Study Companion:</b> ${esc(reply(txt))}</p>`)}else{showPage("assistant");assistantMessage(txt)}return}
 const survey=e.target.closest("[data-survey]");if(survey){let course=survey.dataset.survey;modal("Course feedback",`<div class="modal-body"><p>Share your experience in <b>${esc(course)}</b>. Your answers are intended to be anonymous.</p><label>How clear were course explanations?<select><option>5 — Very clear</option><option>4 — Clear</option><option>3 — Neutral</option><option>2 — Unclear</option><option>1 — Very unclear</option></select></label><label>How useful were materials?<select><option>5 — Very useful</option><option>4 — Useful</option><option>3 — Neutral</option><option>2 — Not very useful</option><option>1 — Not useful</option></select></label><label>Comments<textarea rows="3" placeholder="Optional feedback..."></textarea></label><p><b>Anonymous feedback:</b> This preview does not send data to a server.</p></div>`,"Submit demo feedback",()=>toast("Feedback preview submitted locally"));return}
 if(e.target.matches("[data-upload]"))modal("Upload supporting document",`<div class="modal-body"><label>Choose file<input type="file"></label><p>Upload will be connected to secure storage later.</p></div>`,"Continue",()=>toast("File upload is a UI preview only"));
});
document.querySelectorAll(".nav[data-page],.mobile-nav [data-page]").forEach(b=>b.addEventListener("click",()=>showPage(b.dataset.page)));
document.querySelectorAll(".tab").forEach(b=>b.addEventListener("click",()=>{document.querySelectorAll(".tab").forEach(x=>x.classList.toggle("active",x===b));document.querySelectorAll(".home-tab").forEach(x=>x.classList.toggle("active",x.id==="tab-"+b.dataset.tab))}));
$("mobileMenu").addEventListener("click",()=>$("sidebar").classList.toggle("mobile-open"));
$("profileShortcut").addEventListener("click",()=>{showPage("home");document.querySelector('[data-tab="profile"]').click()});
$("settingsShortcut").addEventListener("click",()=>{showPage("home");document.querySelector('[data-tab="settings"]').click()});
$("langButton").addEventListener("click",()=>$("langMenu").classList.toggle("open"));
document.querySelectorAll("[data-lang]").forEach(b=>b.addEventListener("click",()=>setLang(b.dataset.lang)));
document.querySelectorAll("[data-theme]").forEach(b=>b.addEventListener("click",()=>{let theme=b.dataset.theme;document.body.classList.toggle("dark",theme==="dark"||(theme==="system"&&matchMedia("(prefers-color-scheme: dark)").matches));document.querySelectorAll("[data-theme]").forEach(x=>x.classList.toggle("selected",x===b));toast("Theme preview: "+theme)}));
$("saveSettings").addEventListener("click",()=>toast("Preferences preview saved in this browser session"));
$("profileForm").addEventListener("submit",e=>{e.preventDefault();toast("Profile preview saved locally")});
$("uploadPhoto").addEventListener("click",()=>modal("Upload profile photo",`<div class="modal-body"><label>Select a photo<input type="file" accept="image/png,image/jpeg"></label><p>JPG or PNG · up to 5 MB.</p></div>`,"Preview upload",()=>toast("Photo upload is not connected to a server")));
$("notify").addEventListener("click",()=>modal("Notifications",`<div class="modal-body"><p><b>Assignment 4 due soon</b><br>Database Systems · October 29</p><p><b>New grade published</b><br>Machine Learning Quiz 2 · 18/20</p><p><b>Instructor message</b><br>Dr. Elena Kim replied to your question.</p></div>`,"Mark as read",()=>toast("Notifications marked read in this preview")));
document.querySelectorAll("[data-page='messages']").forEach(b=>b.addEventListener("click",()=>showPage("messages")));
$("scoreSlider").addEventListener("input",updateSimulator);$("hoursSlider").addEventListener("input",updateSimulator);$("ontimeSlider").addEventListener("input",updateSimulator);
$("resetSimulator").addEventListener("click",()=>{$("scoreSlider").value=80;$("hoursSlider").value=5;$("ontimeSlider").value=80;updateSimulator();toast("Simulator reset")});
$("editTarget").addEventListener("click",()=>modal("Set your target grade",`<div class="modal-body"><label>Target score (0–100)<input type="number" id="targetInput" min="0" max="100" value="${target}"></label></div>`,"Save target",()=>{let input=$("targetInput");if(input){target=Math.max(0,Math.min(100,+input.value||90));$("targetGrade").textContent=target>=90?"A−":target>=85?"B+":target>=80?"B":"C";$("neededPoints").textContent=target<=81?"You are at or above your target":`Aim for ${Math.min(100,target+4)}% on remaining work`;toast("Target updated locally")}}));
document.querySelectorAll(".step-list input").forEach(c=>c.addEventListener("change",()=>{$("stepCount").textContent=`${document.querySelectorAll(".step-list input:checked").length}/4`;c.parentElement.style.opacity=c.checked?".58":"1"}));
$("performanceCourse").addEventListener("change",e=>toast("Showing illustrative insights for "+e.target.value));
$("downloadTranscript").addEventListener("click",downloadCSV);$("transcriptBtn").addEventListener("click",downloadCSV);
$("exportCalendar").addEventListener("click",()=>{let rows=[["Date","Event","Course","Time"],...events.map(e=>[`${e.month}/${e.day}/${calendarYear}`,e.title,e.course,e.time])];let blob=new Blob([rows.map(r=>r.join(",")).join("\r\n")],{type:"text/csv"});let url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download="sample-calendar.csv";a.click();URL.revokeObjectURL(url);toast("Sample calendar exported")});
$("addReminder").addEventListener("click",()=>modal("Add personal reminder",`<div class="modal-body"><label>Reminder title<input id="reminderTitle" placeholder="e.g. Review lecture notes"></label><label>Date<input type="date" id="reminderDate"></label><label>Notes<textarea rows="2" placeholder="Optional details"></textarea></label></div>`,"Add reminder",()=>toast("Reminder preview created locally")));
$("calPrev").addEventListener("click",()=>{calendarMonth--;if(calendarMonth<1){calendarMonth=12;calendarYear--}renderCalendar()});$("calNext").addEventListener("click",()=>{calendarMonth++;if(calendarMonth>12){calendarMonth=1;calendarYear++}renderCalendar()});$("calToday").addEventListener("click",()=>{calendarMonth=10;calendarYear=2026;calendarView="Month";document.querySelectorAll("[data-view]").forEach(b=>b.classList.toggle("selected",b.dataset.view==="Month"));renderCalendar()});
document.querySelectorAll("[data-view]").forEach(b=>b.addEventListener("click",()=>{calendarView=b.dataset.view;document.querySelectorAll("[data-view]").forEach(x=>x.classList.toggle("selected",x===b));renderCalendar()}));
document.querySelectorAll("[data-course],[data-type]").forEach(b=>b.addEventListener("change",renderCalendar));
$("search").addEventListener("keydown",e=>{if(e.key==="Enter"){let q=e.target.value.toLowerCase();showPage("courses");document.querySelectorAll("#allCourses .course-card").forEach(c=>c.style.display=c.dataset.course.toLowerCase().includes(q)?"":"none")}});
$("aiFab").addEventListener("click",()=>$("aiWidget").classList.toggle("open"));$("closeWidget").addEventListener("click",()=>$("aiWidget").classList.remove("open"));
$("widgetForm").addEventListener("submit",e=>{e.preventDefault();let txt=$("widgetInput").value.trim();if(!txt)return;$("widgetBody").insertAdjacentHTML("beforeend",`<p><b>You:</b> ${esc(txt)}</p><p><b>Study Companion:</b> ${esc(reply(txt))}</p>`);$("widgetInput").value=""});
$("chatForm").addEventListener("submit",e=>{e.preventDefault();let txt=$("chatInput").value.trim();if(!txt)return;$("chatMessages").insertAdjacentHTML("beforeend",`<div class="bubble sent">${esc(txt)}<small>Just now · Read</small></div><div class="bubble received">${esc(reply(txt))}<small>Just now · Demo assistant</small></div>`);$("chatInput").value="";$("chatMessages").scrollTop=$("chatMessages").scrollHeight});
$("newMessage").addEventListener("click",()=>modal("New message",`<div class="modal-body"><label>To<select><option>Dr. Elena Kim</option><option>Academic Advisor</option><option>Database Systems</option></select></label><label>Message<textarea rows="3" placeholder="Write your message..."></textarea></label></div>`,"Start conversation",()=>toast("New message preview created")));
document.querySelectorAll(".conversation").forEach(b=>b.addEventListener("click",()=>{document.querySelectorAll(".conversation").forEach(x=>x.classList.toggle("active",x===b));currentContact=b.dataset.contact;$("contactName").textContent=currentContact;$("detailName").textContent=currentContact;$("conversationBody").innerHTML=`<div class="bubble received">Welcome to the ${esc(currentContact)} conversation. This is sample content for the message interface.<small>Just now</small></div>`}));
$("messageForm").addEventListener("submit",e=>{e.preventDefault();let txt=$("messageInput").value.trim();if(!txt)return;$("conversationBody").insertAdjacentHTML("beforeend",`<div class="bubble sent">${esc(txt)}<small>Just now · Sent in preview</small></div>`);$("messageInput").value=""});
$("conversationSearch").addEventListener("input",e=>{let q=e.target.value.toLowerCase();document.querySelectorAll(".conversation").forEach(b=>b.style.display=b.dataset.contact.toLowerCase().includes(q)?"":"none")});
$("addStudyBlock").addEventListener("click",()=>modal("Add study block",`<div class="modal-body"><label>Study task<input placeholder="e.g. Review regression diagnostics"></label><label>Duration<select><option>25 minutes</option><option>45 minutes</option><option>60 minutes</option><option>90 minutes</option></select></label></div>`,"Add block",()=>toast("Study block preview added")));
$("supportBtn").addEventListener("click",()=>modal("Contact support",`<div class="modal-body"><label>Topic<select><option>Portal access</option><option>Academic records</option><option>Course registration</option><option>Other</option></select></label><label>Describe the issue<textarea rows="3" placeholder="How can we help?"></textarea></label></div>`,"Send demo request",()=>toast("Support request preview recorded locally")));
$("prevWeek").addEventListener("click",()=>toast("Previous week preview selected"));$("nextWeek").addEventListener("click",()=>toast("Next week preview selected"));$("todayWeek").addEventListener("click",()=>toast("Returned to current sample week"));
document.addEventListener("keydown",e=>{if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==="k"){e.preventDefault();$("search").focus()}if(e.key==="Escape"){$("modalBackdrop").hidden=true;$("aiWidget").classList.remove("open");$("sidebar").classList.remove("mobile-open")}});
renderCourses();renderGrades();renderAttendance();renderCalendar();updateSimulator();
