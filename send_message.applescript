-- send_message.applescript
-- Usage (from Python or Terminal): osascript send_message.applescript "+19195551234" "Hello there"
on run argv
	if (count of argv) < 2 then
		error "Usage: osascript send_message.applescript \"+15555551234\" \"Message text\""
	end if
	set targetPhone to item 1 of argv
	set theText to item 2 of argv
	
	tell application "Messages"
		-- Try to reuse an existing chat if possible
		set existingChats to chats whose id contains targetPhone or name contains targetPhone
		if (count of existingChats) > 0 then
			set theChat to item 1 of existingChats
		else
			-- Create a new chat with the target participant; Messages will choose the right service (iMessage/SMS)
			set theChat to make new text chat with properties {participants:{targetPhone}}
			delay 0.3
		end if
		send theText to theChat
	end tell
end run
