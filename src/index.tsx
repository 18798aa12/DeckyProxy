import { definePlugin } from "@decky/api";
import { staticClasses } from "@decky/ui";
import { FaNetworkWired } from "react-icons/fa";
import { App } from "./App";

export default definePlugin(() => ({
  name: "DeckyProxy",
  titleView: <div className={staticClasses.Title}>DeckyProxy</div>,
  content: <App />,
  // Decky hides QAM content while native dialogs are open. Keep the picker
  // callback's owner mounted; App pauses background polling while hidden.
  alwaysRender: true,
  icon: <FaNetworkWired />,
}));
