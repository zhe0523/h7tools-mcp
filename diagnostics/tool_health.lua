-- Read-only H7-TOOL health script for manual execution in the Lua page.
-- It intentionally does not reset, power-cycle, erase, program, change GPIO,
-- or start a measurement path. It is compatible with the V1.0 Lua API manual.

print("H7TOOL_DIAG_BEGIN")

if get_hard_info ~= nil then
  local board, lcd, height, width, ui = get_hard_info()
  print(string.format("hardware board=%s lcd=%s display=%sx%s ui=%s", tostring(board), tostring(lcd), tostring(width), tostring(height), tostring(ui)))
else
  print("hardware info API unavailable")
end

if read_clock ~= nil then
  local year, month, day, hour, minute, second, week = read_clock()
  print(string.format("clock=%04d-%02d-%02dT%02d:%02d:%02d week=%s", year, month, day, hour, minute, second, tostring(week)))
end

if get_runtime ~= nil then
  print(string.format("uptime_ms=%s", tostring(get_runtime())))
end

print("H7TOOL_DIAG_END")
