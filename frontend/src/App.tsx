import { ScheduledCallsPage } from './components/ScheduledCalls/ScheduledCallsPage';
import { ThemeProvider } from './context/ThemeContext';

function App() {
  return (
    <ThemeProvider>
      <ScheduledCallsPage />
    </ThemeProvider>
  );
}

export default App;
