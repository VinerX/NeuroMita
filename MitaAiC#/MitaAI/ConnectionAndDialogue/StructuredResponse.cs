using System.Collections.Generic;
using System.Text.Json;

namespace MitaAI
{
    public class ResponseSegment
    {
        public string text { get; set; } = "";
        public List<string> emotions { get; set; } = new List<string>();
        public List<string> animations { get; set; } = new List<string>();
        public List<string> commands { get; set; } = new List<string>();
        public List<string> movement_modes { get; set; } = new List<string>();
        public List<string> visual_effects { get; set; } = new List<string>();
        public List<string> clothes { get; set; } = new List<string>();
        public List<string> music { get; set; } = new List<string>();
        public List<string> interactions { get; set; } = new List<string>();
        public List<string> face_params { get; set; } = new List<string>();
        public string start_game { get; set; }
        public string end_game { get; set; }
        public string target { get; set; }
        public string hint { get; set; }
        public bool? allow_sleep { get; set; }
    }

    public class StructuredResponse
    {
        public float attitude_change { get; set; }
        public float boredom_change { get; set; }
        public float stress_change { get; set; }
        public List<string> memory_add { get; set; } = new List<string>();
        public List<string> memory_update { get; set; } = new List<string>();
        public List<string> memory_delete { get; set; } = new List<string>();
        public List<ResponseSegment> segments { get; set; } = new List<ResponseSegment>();
        public string response { get; set; } = "";

        /// <summary>
        /// Try to parse structured response from the task result dict.
        /// Returns null if segments are not present.
        /// </summary>
        public static StructuredResponse TryParse(Dictionary<string, JsonElement> data)
        {
            // Check if result contains segments (new task-based format: data["result"]["segments"])
            // or if segments are at top level (flat format: data["segments"])
            JsonElement resultElement;
            Dictionary<string, JsonElement> resultDict = null;

            if (data.TryGetValue("result", out resultElement) && resultElement.ValueKind == JsonValueKind.Object)
            {
                var resultStr = resultElement.GetRawText();
                resultDict = JsonSerializer.Deserialize<Dictionary<string, JsonElement>>(resultStr);
            }

            var source = resultDict ?? data;

            JsonElement segmentsEl;
            if (!source.TryGetValue("segments", out segmentsEl) || segmentsEl.ValueKind != JsonValueKind.Array)
                return null;

            var structured = new StructuredResponse();

            // Parse response text
            JsonElement respEl;
            if (source.TryGetValue("response", out respEl) && respEl.ValueKind == JsonValueKind.String)
                structured.response = respEl.GetString() ?? "";

            // Parse global fields
            structured.attitude_change = GetFloat(source, "attitude_change");
            structured.boredom_change = GetFloat(source, "boredom_change");
            structured.stress_change = GetFloat(source, "stress_change");
            structured.memory_add = GetStringList(source, "memory_add");
            structured.memory_update = GetStringList(source, "memory_update");
            structured.memory_delete = GetStringList(source, "memory_delete");

            // Parse segments
            foreach (var segEl in segmentsEl.EnumerateArray())
            {
                if (segEl.ValueKind != JsonValueKind.Object) continue;
                var segStr = segEl.GetRawText();
                var segDict = JsonSerializer.Deserialize<Dictionary<string, JsonElement>>(segStr);

                var seg = new ResponseSegment();
                JsonElement val;

                if (segDict.TryGetValue("text", out val) && val.ValueKind == JsonValueKind.String)
                    seg.text = val.GetString() ?? "";

                seg.emotions = GetStringList(segDict, "emotions");
                seg.animations = GetStringList(segDict, "animations");
                seg.commands = GetStringList(segDict, "commands");
                seg.movement_modes = GetStringList(segDict, "movement_modes");
                seg.visual_effects = GetStringList(segDict, "visual_effects");
                seg.clothes = GetStringList(segDict, "clothes");
                seg.music = GetStringList(segDict, "music");
                seg.interactions = GetStringList(segDict, "interactions");
                seg.face_params = GetStringList(segDict, "face_params");

                if (segDict.TryGetValue("start_game", out val) && val.ValueKind == JsonValueKind.String)
                    seg.start_game = val.GetString();
                if (segDict.TryGetValue("end_game", out val) && val.ValueKind == JsonValueKind.String)
                    seg.end_game = val.GetString();
                if (segDict.TryGetValue("target", out val) && val.ValueKind == JsonValueKind.String)
                    seg.target = val.GetString();
                if (segDict.TryGetValue("hint", out val) && val.ValueKind == JsonValueKind.String)
                    seg.hint = val.GetString();
                if (segDict.TryGetValue("allow_sleep", out val) && (val.ValueKind == JsonValueKind.True || val.ValueKind == JsonValueKind.False))
                    seg.allow_sleep = val.GetBoolean();

                structured.segments.Add(seg);
            }

            return structured;
        }

        private static float GetFloat(Dictionary<string, JsonElement> dict, string key)
        {
            JsonElement el;
            if (dict.TryGetValue(key, out el) && el.ValueKind == JsonValueKind.Number)
                return (float)el.GetDouble();
            return 0f;
        }

        private static List<string> GetStringList(Dictionary<string, JsonElement> dict, string key)
        {
            var list = new List<string>();
            JsonElement el;
            if (dict.TryGetValue(key, out el) && el.ValueKind == JsonValueKind.Array)
            {
                foreach (var item in el.EnumerateArray())
                {
                    if (item.ValueKind == JsonValueKind.String)
                        list.Add(item.GetString() ?? "");
                }
            }
            return list;
        }
    }
}
