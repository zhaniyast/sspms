export const courseColors = ['#4f6bed', '#14a38b', '#e6a23c', '#a16ae8', '#e36d87', '#219ebc'];
export const courses = [
  { id: 1, code: 'CSS 305', name: 'Database Management Systems 2', teacher: 'Aigerim Sadykova', credits: 5, progress: 74, grade: 82, color: '#4f6bed', deadline: '12 Nov', room: 'B 302', time: '09:00', type: 'Lecture', risk: 'low', students: 36 },
  { id: 2, code: 'CSS 105', name: 'Introduction to Programming', teacher: 'Timur Bekov', credits: 5, progress: 86, grade: 91, color: '#14a38b', deadline: '14 Nov', room: 'A 204', time: '11:00', type: 'Practice', risk: 'low', students: 42 },
  { id: 3, code: 'CSS 356', name: 'Machine Learning', teacher: 'Dana Omarova', credits: 5, progress: 58, grade: 68, color: '#a16ae8', deadline: '10 Nov', room: 'C 101', time: '13:00', type: 'Lab', risk: 'high', students: 28 },
  { id: 4, code: 'MCM 308', name: 'Statistics for Data Science', teacher: 'Arman Kassen', credits: 5, progress: 63, grade: 76, color: '#e6a23c', deadline: '16 Nov', room: 'B 115', time: '15:00', type: 'Lecture', risk: 'medium', students: 32 },
  { id: 5, code: 'CSS 360', name: 'Data Visualization', teacher: 'Mira Tolegen', credits: 5, progress: 79, grade: 85, color: '#e36d87', deadline: '18 Nov', room: 'D 210', time: '16:00', type: 'Practice', risk: 'low', students: 25 },
  { id: 6, code: 'CSS 390', name: 'Software Engineering', teacher: 'Aigerim Sadykova', credits: 5, progress: 48, grade: 72, color: '#219ebc', deadline: '20 Nov', room: 'A 303', time: '10:00', type: 'Lab', risk: 'medium', students: 30 },
];
export const assignments = [
  { id: 1, title: 'Assignment 3 — SQL joins', course: 'CSS 305', due: 'Today, 23:59', points: '20 pts', status: 'In progress', color: '#4f6bed' },
  { id: 2, title: 'Lab 5 — Classification models', course: 'CSS 356', due: '10 Nov', points: '15 pts', status: 'Overdue', color: '#a16ae8' },
  { id: 3, title: 'Visualization mini-project', course: 'CSS 360', due: '18 Nov', points: '25 pts', status: 'Submitted', color: '#e36d87' },
  { id: 4, title: 'Midterm reflection', course: 'MCM 308', due: '21 Nov', points: '10 pts', status: 'Graded', color: '#e6a23c' },
];
export const studentRows = [
  { id: '2400003', name: 'Aydana Nurgali', group: 'DS-2401', grade: 68, attendance: 76, risk: 'High', change: '+12%', reason: '2 missing assignments, activity dropped', last: '3 days ago' },
  { id: '2400017', name: 'Dias Mukhan', group: 'DS-2401', grade: 73, attendance: 81, risk: 'High', change: '+8%', reason: 'Late submissions increased', last: 'Yesterday' },
  { id: '2400028', name: 'Aruzhan Sapar', group: 'DS-2402', grade: 79, attendance: 84, risk: 'Medium', change: '+3%', reason: 'Attendance is approaching the limit', last: '5 days ago' },
  { id: '2400036', name: 'Nursultan Ali', group: 'DS-2401', grade: 91, attendance: 96, risk: 'Low', change: '−4%', reason: 'Stable activity and results', last: 'Today' },
  { id: '2400042', name: 'Madina Serik', group: 'DS-2403', grade: 88, attendance: 92, risk: 'Low', change: '−2%', reason: 'Consistent submissions', last: '2 days ago' },
  { id: '2400051', name: 'Alikhan Bek', group: 'DS-2402', grade: 64, attendance: 71, risk: 'High', change: '+15%', reason: 'Low attendance and missing work', last: '1 week ago' },
];
export const messages = [
  { id: 1, name: 'Aigerim Sadykova', role: 'Teacher · CSS 305', text: 'Please review the SQL joins materials before class.', time: '10:42', unread: 2, initials: 'AS', color: '#4f6bed' },
  { id: 2, name: 'CSS 356 Course chat', role: 'Course group', text: 'Dana: Lab 5 rubric is available now.', time: 'Yesterday', unread: 0, initials: 'ML', color: '#a16ae8' },
  { id: 3, name: 'Academic Advisor', role: 'Advising', text: 'Let us schedule a short check-in this week.', time: 'Mon', unread: 1, initials: 'AA', color: '#14a38b' },
];
export const notifications = [
  { id: 1, title: 'New grade published', detail: 'Midterm reflection · MCM 308', time: '10 min ago', type: 'grade', unread: true },
  { id: 2, title: 'Assignment deadline soon', detail: 'SQL joins · CSS 305', time: '1 hour ago', type: 'deadline', unread: true },
  { id: 3, title: 'New course material', detail: 'Week 9 slides · CSS 356', time: 'Yesterday', type: 'material', unread: false },
];
export const weeklyRisk = [
  { week: 'W1', risk: 31, activity: 78 }, { week: 'W2', risk: 28, activity: 82 }, { week: 'W3', risk: 34, activity: 75 },
  { week: 'W4', risk: 39, activity: 71 }, { week: 'W5', risk: 44, activity: 66 }, { week: 'W6', risk: 41, activity: 69 },
  { week: 'W7', risk: 52, activity: 58 }, { week: 'W8', risk: 62, activity: 48 }, { week: 'W9', risk: 56, activity: 57 },
];
export const weekDays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'];
export const schedule = [
  { day: 0, start: 9, duration: 1.5, course: courses[0], room: 'B 302', teacher: 'A. Sadykova' },
  { day: 1, start: 11, duration: 1.5, course: courses[1], room: 'A 204', teacher: 'T. Bekov' },
  { day: 2, start: 13, duration: 2, course: courses[2], room: 'C 101', teacher: 'D. Omarova' },
  { day: 3, start: 15, duration: 1.5, course: courses[3], room: 'B 115', teacher: 'A. Kassen' },
  { day: 4, start: 10, duration: 1.5, course: courses[4], room: 'D 210', teacher: 'M. Tolegen' },
  { day: 0, start: 14, duration: 1.5, course: courses[5], room: 'A 303', teacher: 'A. Sadykova' },
];
