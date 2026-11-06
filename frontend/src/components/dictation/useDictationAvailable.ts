import { useQuery } from "@tanstack/react-query";
import { dictationApi } from "../../api/dictation";

/** Whether this build can dictate: a microphone API and the speech model shipped with the app. */
export function useDictationAvailable(): boolean {
  const supported = typeof navigator !== "undefined" && Boolean(navigator.mediaDevices?.getUserMedia);
  const { data } = useQuery({ queryKey: ["dictation-status"], queryFn: ({ signal }) => dictationApi.status(signal), staleTime: Infinity, retry: false, enabled: supported });
  return supported && Boolean(data?.available);
}
