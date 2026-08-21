import "@/App.css";
import { Toaster } from "@/components/ui/sonner";
import Studio from "@/components/studio/Studio";

function App() {
  return (
    <div className="App">
      <Studio />
      <Toaster theme="dark" position="bottom-right" richColors />
    </div>
  );
}

export default App;
