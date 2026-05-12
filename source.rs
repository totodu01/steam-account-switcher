#![windows_subsystem = "windows"]
use eframe::egui;
use winreg::RegKey;
use base64::Engine;
use clipboard::ClipboardProvider;
fn main() -> eframe::Result<()> {
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_inner_size([280.0, 100.0])
            .with_resizable(true),
        ..Default::default()
    };
    eframe::run_native(
        "CS2NFA.SHOP Steam Tool",
        options,
        Box::new(|_cc| Box::new(MyApp::default())),
    )
}
#[derive(Default)]
struct MyApp {
    status: String,
}
impl eframe::App for MyApp {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        egui::CentralPanel::default().show(ctx, |ui| {
            ui.vertical_centered(|ui| {
                ui.add_space(10.0);
                
                ui.horizontal(|ui| {
                    if ui
                        .add_sized([120.0, 30.0], egui::Button::new("Add Account"))
                        .clicked()
                    {
                        self.status = match handle_add_account() {
                            Ok(msg) => msg,
                            Err(err) => err,
                        };
                    }
                    ui.add_space(6.0);
                    if ui
                        .add_sized([120.0, 30.0], egui::Button::new("Clear Steam"))
                        .clicked()
                    {
                            self.status = match handle_clear_steam() {
                            Ok(msg) => msg,
                            Err(err) => err,
                        };
                    }
                });
                ui.add_space(6.0); 
                
                ui.label(&self.status);
            });
        });
    }
}
use std::fs;
fn get_steam_path() -> Result<String, String> {
    let hkcu = RegKey::predef(winreg::enums::HKEY_CURRENT_USER);
    let steam_key = hkcu
        .open_subkey("SOFTWARE\\Valve\\Steam")
        .map_err(|e| e.to_string())?;
    let path: String = steam_key
        .get_value("SteamPath")
        .map_err(|e| e.to_string())?;
    Ok(path)
}
fn handle_clear_steam() -> Result<String, String> {
    let steam_path = get_steam_path().map_err(|e| e)?;
    let config_dir = std::path::Path::new(&steam_path).join("config");
    let config_vdf = config_dir.join("config.vdf");
    let loginusers_vdf = config_dir.join("loginusers.vdf");
    let base_path = std::path::Path::new(&std::env::var("LOCALAPPDATA").unwrap())
    .join("Steam");delete_steam_files_and_folder(&config_dir, &base_path)?;
    kill_steam_process()?;
    delete_steam_files_and_folder(&config_dir, &base_path)?;
    Ok(format!("Cleared Steam."))
}
fn handle_add_account() -> Result<String, String> {
    
    let mut clipboard = clipboard::ClipboardContext::new()
        .map_err(|_| "Clipboard not available")?;
    let content = clipboard
        .get_contents()
        .map_err(|_| "Failed to read clipboard")?;
    
    let (username, jwt) = parse_clipboard(&content)?;
    
    let steamid = extract_steamid_from_jwt(&jwt)?;
    
    let steam_path = get_steam_path().map_err(|e| e)?;
    let config_dir = std::path::Path::new(&steam_path).join("config");
    let config_vdf = config_dir.join("config.vdf");
    let loginusers_vdf = config_dir.join("loginusers.vdf");
    check_steam_config_files(&config_dir)?;
    kill_steam_process()?;
    
    inject_account_into_config(&config_vdf, &username, &steamid)?;
    
    update_loginusers_vdf(&loginusers_vdf, &username, &steamid)?;
    write_local_vdf(&username, &jwt)?;
    write_localconfig_vdf(&steamid)?;
    write_autologin_user(&username)?;
    Ok(format!("Account '{}' added successfully. Open Steam.", username))
}
fn parse_clipboard(input: &str) -> Result<(String, String), String> {
    let mut parts = input.trim().split("----");
    let username = parts
        .next()
        .ok_or("Missing username")?;
    let token = parts
        .next()
        .ok_or("Missing token")?;
    Ok((username.to_string(), token.to_string()))
}
fn extract_steamid_from_jwt(jwt: &str) -> Result<String, String> {
    let parts: Vec<&str> = jwt.split('.').collect();
    if parts.len() != 3 {
        return Err("Invalid JWT format".into());
    }
    let payload = base64::engine::general_purpose::URL_SAFE_NO_PAD
        .decode(parts[1])
        .map_err(|_| "Failed to decode JWT payload")?;
    let json: serde_json::Value =
        serde_json::from_slice(&payload).map_err(|_| "Invalid JWT JSON")?;
    let steamid = json
        .get("sub")
        .and_then(|v| v.as_str())
        .ok_or("JWT missing sub field")?;
    Ok(steamid.to_string())
}
fn inject_account_into_config(
    path: &std::path::Path,
    username: &str,
    steamid: &str,
) -> Result<(), String> {
    let mut content = std::fs::read_to_string(path)
        .map_err(|_| "Failed to read config.vdf")?;
    
    if content.contains(&format!("\"SteamID\"\t\t\"{}\"", steamid)) {
        return Err("SteamID already exists in config".into());
    }
    let accounts_block = format!(
        "\n\t\t\t\t\t\"{}\"\n\t\t\t\t\t{{\n\t\t\t\t\t\t\"SteamID\"\t\t\"{}\"\n\t\t\t\t\t}}\n",
        username, steamid
    );
    let insert_pos = content
        .rfind("\"Accounts\"")
        .and_then(|i| content[i..].find('{').map(|o| i + o + 1))
        .ok_or("Accounts block not found")?;
    content.insert_str(insert_pos, &accounts_block);
    std::fs::write(path, content)
        .map_err(|_| "Failed to write config.vdf")?;
    Ok(())
}
fn current_timestamp() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs()
        .to_string()
}
fn update_loginusers_vdf(
    path: &std::path::Path,
    username: &str,
    steamid: &str,
) -> Result<(), String> {
    let mut content =
        std::fs::read_to_string(path).map_err(|_| "Failed to read loginusers.vdf")?;
    
    content = content.replace(
        "\"MostRecent\"\t\t\"1\"",
        "\"MostRecent\"\t\t\"0\"",
    );
    
    if content.contains(&format!("\"{}\"", steamid)) {
        content = update_existing_user(&content, username, steamid)?;
    } else {
        content = insert_new_user(&content, username, steamid)?;
    }
    std::fs::write(path, content).map_err(|_| "Failed to write loginusers.vdf")?;
    Ok(())
}
fn update_existing_user(
    content: &str,
    username: &str,
    steamid: &str,
) -> Result<String, String> {
    let mut result = String::new();
    let mut lines = content.lines();
    while let Some(line) = lines.next() {
        result.push_str(line);
        result.push('\n');
        if line.contains(&format!("\"{}\"", steamid)) {
            
            while let Some(inner) = lines.next() {
                if inner.contains("\"AccountName\"") {
                    result.push_str(&format!(
                        "\t\t\t\"AccountName\"\t\t\"{}\"\n",
                        username
                    ));
                } else if inner.contains("\"PersonaName\"") {
                    result.push_str(&format!(
                        "\t\t\t\"PersonaName\"\t\t\"{}\"\n",
                        username
                    ));
                } else if inner.contains("\"MostRecent\"") {
                    result.push_str("\t\t\t\"MostRecent\"\t\t\"1\"\n");
                } else if inner.contains("\"Timestamp\"") {
                    result.push_str(&format!(
                        "\t\t\t\"Timestamp\"\t\t\"{}\"\n",
                        current_timestamp()
                    ));
                } else {
                    result.push_str(inner);
                    result.push('\n');
                }
                if inner.trim() == "}" {
                    break;
                }
            }
        }
    }
    Ok(result)
}
fn insert_new_user(
    content: &str,
    username: &str,
    steamid: &str,
) -> Result<String, String> {
let insert_block = format!(
    r#"
	"{steamid}"
	{{
		"AccountName"		"{username}"
		"PersonaName"		"{username}"
		"RememberPassword"		"1"
		"WantsOfflineMode"		"0"
		"SkipOfflineModeWarning"		"0"
		"AllowAutoLogin"		"1"
		"MostRecent"		"1"
		"Timestamp"		"{timestamp}"
	}}
"#,
    steamid = steamid,
    username = username,
    timestamp = current_timestamp()
);
    let pos = content
        .rfind('}')
        .ok_or("Invalid loginusers.vdf format")?;
    let mut new_content = content.to_string();
    new_content.insert_str(pos, &insert_block);
    Ok(new_content)
}
fn compute_crc32(data: &str) -> String {
    let crc32_value = crc32fast::hash(data.as_bytes());
    let hex = format!("{:08x}", crc32_value);
    let trimmed = hex.trim_start_matches('0');
    
    let result = if trimmed.is_empty() {
        "01".to_string()
    } else {
        format!("{}1", trimmed)
    };
    
    println!("CRC32 for '{}': {}", data, result);
    
    result
}
use windows::Win32::Security::Cryptography::{CryptProtectData, CRYPT_INTEGER_BLOB};
fn steam_encrypt(token: &str, account_name: &str) -> Result<String, String> {
    
    let data_to_encrypt = token.as_bytes();
    
    let byte_string = b"B\x00O\x00b\x00f\x00u\x00s\x00c\x00a\x00t\x00e\x00B\x00u\x00f\x00f\x00e\x00r\x00\x00\x00";
    
    let account_name_bytes = account_name.as_bytes();
    
    let data_in = CRYPT_INTEGER_BLOB {
        cbData: data_to_encrypt.len() as u32,
        pbData: data_to_encrypt.as_ptr() as *mut u8,
    };
    
    let entropy = CRYPT_INTEGER_BLOB {
        cbData: account_name_bytes.len() as u32,
        pbData: account_name_bytes.as_ptr() as *mut u8,
    };
    
    let description = String::from_utf8_lossy(byte_string);
    let description_wide: Vec<u16> = description.encode_utf16().chain(Some(0)).collect();
    let description_pcwstr = windows::core::PCWSTR(description_wide.as_ptr());
    
    let mut data_out = CRYPT_INTEGER_BLOB::default();
    
    unsafe {
        
        let success = CryptProtectData(
            &data_in,
            description_pcwstr,
            Some(&entropy),
            None,
            0x11, 
            &mut data_out,
        );
        
        if success.is_err() {
            return Err("CryptProtectData failed".to_string());
        }
        
        let encrypted_slice = std::slice::from_raw_parts(
            data_out.pbData,
            data_out.cbData as usize,
        );
        let hex_string = encrypted_slice.iter()
            .map(|b| format!("{:02x}", b))
            .collect::<String>();
        
        #[link(name = "kernel32")]
        unsafe extern "system" {
            fn LocalFree(hmem: *mut std::ffi::c_void) -> *mut std::ffi::c_void;
        }
        LocalFree(data_out.pbData as *mut std::ffi::c_void);
        
        println!("Encrypted token (hex): {}", hex_string);
        
        Ok(hex_string)
    }
}
fn write_local_vdf(username: &str, token: &str) -> Result<(), String> {
    let crc = compute_crc32(username);
    let encrypted = steam_encrypt(token, username)?;
    let base_path = std::path::Path::new(&std::env::var("LOCALAPPDATA").unwrap())
        .join("Steam");
    let path = base_path.join("local.vdf");
    std::fs::create_dir_all(&base_path)
        .map_err(|_| "Failed to create Steam directory")?;
    let content = if path.exists() {
        let existing = std::fs::read_to_string(&path)
            .map_err(|_| "Failed to read local.vdf")?;
        inject_connect_cache(&existing, &crc, &encrypted)?
    } else {
        create_new_local_vdf(&crc, &encrypted)
    };
    std::fs::write(path, content)
        .map_err(|_| "Failed to write local.vdf")?;
    Ok(())
}
fn inject_connect_cache(
    content: &str,
    crc: &str,
    encrypted: &str,
) -> Result<String, String> {
    let mut output = String::new();
    let mut lines = content.lines().peekable();
    let mut in_connect_cache = false;
    let mut brace_depth = 0;
    let mut replaced = false;
    while let Some(line) = lines.next() {
        let trimmed = line.trim();
        if trimmed == "\"ConnectCache\"" {
            in_connect_cache = true;
            brace_depth = 0;
            output.push_str(line);
            output.push('\n');
            continue;
        }
        if in_connect_cache {
            if trimmed.starts_with('{') {
                brace_depth += 1;
            } else if trimmed.starts_with('}') {
                brace_depth -= 1;
                
                if brace_depth == 0 && !replaced {
                    output.push_str(&format!(
                        "\t\t\t\t\t\"{}\"\t\t\"{}\"\n",
                        crc, encrypted
                    ));
                    replaced = true;
                }
            }
            
            if trimmed.starts_with(&format!("\"{}\"", crc)) {
                output.push_str(&format!(
                    "\t\t\t\t\t\"{}\"\t\t\"{}\"\n",
                    crc, encrypted
                ));
                replaced = true;
                continue;
            }
        }
        output.push_str(line);
        output.push('\n');
    }
    if !replaced {
        return Err("ConnectCache block not found".into());
    }
    Ok(output)
}
fn create_new_local_vdf(crc: &str, encrypted: &str) -> String {
    format!(
r#""MachineUserConfigStore"
{{
	"Software"
	{{
		"Valve"
		{{
			"Steam"
			{{
				"ConnectCache"
				{{
					"{crc}"		"{encrypted}"
				}}
			}}
		}}
	}}
}}
"#,
        crc = crc,
        encrypted = encrypted
    )
}
fn steamid64_to_steamid3(steamid64: &str) -> Result<String, String> {
    let id64: u64 = steamid64
        .parse()
        .map_err(|_| "Invalid SteamID64")?;
    if id64 < 76561197960265728 {
        return Err("SteamID64 too small".into());
    }
    Ok((id64 - 76561197960265728).to_string())
}
fn write_localconfig_vdf(steamid64: &str) -> Result<(), String> {
    let steamid3 = steamid64_to_steamid3(steamid64)?;
    let content = format!(
r#""UserLocalConfigStore"
{{
	"friends"
	{{
		"SignIntoFriends" "1"
	}}
	"WebStorage"
	{{
		"FriendStoreLocalPrefs_{steamid3}" "{{\"ePersonaState\":7,\"strNonFriendsAllowedToMsg\":\"\"}}"
	}}
}}
"#,
        steamid3 = steamid3
    );
    let path = std::path::Path::new("C:\\Program Files (x86)\\Steam")
        .join("userdata")
        .join(&steamid3)
        .join("config")
        .join("localconfig.vdf");
    std::fs::create_dir_all(path.parent().unwrap())
        .map_err(|_| "Failed to create userdata config directory")?;
    std::fs::write(path, content)
        .map_err(|_| "Failed to write localconfig.vdf")?;
    Ok(())
}
use windows::Win32::System::Registry::{
    RegSetValueExW, RegOpenKeyExW, RegCloseKey, HKEY_CURRENT_USER, KEY_SET_VALUE, REG_SZ, HKEY
};
fn write_autologin_user(account_name: &str) -> Result<(), String> {
    unsafe {
        
        let subkey_path: Vec<u16> = "SOFTWARE\\Valve\\Steam\0"
            .encode_utf16()
            .collect();
        
        let value_name: Vec<u16> = "AutoLoginUser\0"
            .encode_utf16()
            .collect();
        
        let account_name_wide: Vec<u16> = account_name
            .encode_utf16()
            .chain(Some(0))
            .collect();
        
        let mut hkey = HKEY::default();
        let result = RegOpenKeyExW(
            HKEY_CURRENT_USER,
            windows::core::PCWSTR(subkey_path.as_ptr()),
            0,
            KEY_SET_VALUE,
            &mut hkey,
        );
        
        if result.is_err() {
            return Err(format!("Failed to open registry key: {:?}", result.err()));
        }
        
        let data_slice = std::slice::from_raw_parts(
            account_name_wide.as_ptr() as *const u8,
            account_name_wide.len() * 2,
        );
        
        let set_result = RegSetValueExW(
            hkey,
            windows::core::PCWSTR(value_name.as_ptr()),
            0,
            REG_SZ,
            Some(data_slice),
        );
        
        let _ = RegCloseKey(hkey);
        
        if set_result.is_err() {
            return Err(format!("Failed to set registry value: {:?}", set_result.err()));
        }
        
        Ok(())
    }
}
use std::process::Command;
fn kill_steam_process() -> Result<(), String> {
    
    let hkcu = RegKey::predef(winreg::enums::HKEY_CURRENT_USER);
    let steam_key = hkcu
        .open_subkey("SOFTWARE\\Valve\\Steam\\ActiveProcess")
        .map_err(|e| format!("Failed to open Steam registry key: {}. Steam may not be installed or running.", e))?;
    
    let pid: u32 = steam_key
        .get_value("pid")
        .map_err(|e| format!("Failed to read PID from registry: {}. Steam may not be running.", e))?;
    
    if pid == 0 {
        return Err("Invalid PID (0) found in registry.".to_string());
    }
    
    println!("Found Steam PID: {}", pid);
    
    let output = Command::new("taskkill")
        .args(&["/F", "/PID", &pid.to_string(), "/T"])
        .output()
        .map_err(|e| format!("Failed to execute taskkill: {}", e))?;
    
    if output.status.success() {
        let stdout = String::from_utf8_lossy(&output.stdout);
        println!("Successfully killed Steam process: {}", stdout.trim());
        
        std::thread::sleep(std::time::Duration::from_millis(1000));
        
        Ok(())
    } else {
        let stderr = String::from_utf8_lossy(&output.stderr);
        
        if stderr.to_lowercase().contains("not found") || stderr.to_lowercase().contains("no running instance") {
            println!("Steam process not found. Nothing to kill.");
            Ok(())
        } else {
            Err(format!("Failed to kill Steam process: {}", stderr.trim()))
        }
    }
}
use std::path::Path;
fn check_steam_config_files(config_dir: &Path) -> Result<(), String> {
    let config_vdf = config_dir.join("config.vdf");
    let loginusers_vdf = config_dir.join("loginusers.vdf");
    if !config_vdf.exists() || !loginusers_vdf.exists() {
        return Err("Please open Steam and login to any account first to create the necessary config files.".into());
    }
    Ok(())
}
fn delete_steam_files_and_folder(config_dir: &Path, steam_base_dir: &Path) -> Result<(), String> {
    let config_vdf = config_dir.join("config.vdf");
    let loginusers_vdf = config_dir.join("loginusers.vdf");
    
    if config_vdf.exists() {
        fs::remove_file(&config_vdf)
            .map_err(|e| format!("Failed to delete config.vdf: {}", e))?;
    }
    
    if loginusers_vdf.exists() {
        fs::remove_file(&loginusers_vdf)
            .map_err(|e| format!("Failed to delete loginusers.vdf: {}", e))?;
    }
    
    if steam_base_dir.exists() {
        
        fs::remove_dir_all(&steam_base_dir)
            .map_err(|e| format!("Failed to delete Steam folder and contents: {}", e))?;
    }
    Ok(())
}