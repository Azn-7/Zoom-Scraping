### REWORK TIME

### Table of Contents

- Introduction
  - How does it work?
  - How long may this take to function?
  - What to expect?
  - Who is it intended for?
- I: DocsToSheet (Retreiving zoom links from google docs)
- II: ZoomDownloader

<!-- ———————————————————————————————— Introduction ———————————————————————————————— -->

# Introduction:

Zoom Scraping was a projected develop with the intention to retrieve zoom recordings from google docs and parsing all links to be downloadable mp4/m4a files. As there can be many zoom recordings that may need of its videos to be downloaded and you might not be the owner of the video uploaded, it'll help allow you to automate the process of downloading any downloadable files from any zoom recordings. This project involves a two step process and the first one can be skipped if the zoom links are already obtained.

If you run to any problems or have any questions, feel free to email me at ttiet777@gmail.com.

### Some questions you may have answered here

> How does it work?

The program is designed to take any zoom links that redirects to a zoom recording, and automatically downloads any files that the recording is able to provide. In a zoom recording on the top right, it may prompt an option to download the recordings .mp4 (video), .m4a (audio only), or .vtt (transcript). Normally, a user would have to visit the recording link, and click on the download button. But with the help of SeleniumLibrary, it allows the program to act as the user itself, and follow the same steps as a person would, but automated. This program will organize all downloaded files to its respective folder managed by the user, a visual example shown is below.

<img src = "images/Diagram of zoomDownloader.py.png">

Whether the program organizes downloads into per-document subfolders or drops them all into a single flat folder depends on how "zoom_links.txt" is formatted (see the note under "II: ZoomDownloader" below). A solution to generating that file, if wished, is included in "I: DocsToSheet" below step 14.

> How long may this take to function?

Expected time if following the two step instructions (DocsToSheet & ZoomDownloader) would be 30 minutes minimum. Each recordings being parsed will take at least 40 seconds per link. As such, the estimated time for the overall download process follows this formula

    40 * (Number of Links) = Minimum of the total time

> What to expect?

After running the program, it'll be able to download all files from each zoom recordings and output the files to a designated file PATH. If "zoom_links.txt" includes a Document Title column, it'll create a subfolder per document and name each file after its hyperlink title; otherwise all files download flat into that PATH, prefixed with their hyperlink title. A few things to note as well...

- You can modify which files to exclude (such as .m4a and .vtt)
- You may run this program headless if wishing to see how the program function
- When it downloads a file, it

> Who is this intended for?

If you're someone who needs to download the files attached to the many zoom recordings you may have, this is for you! This is especially important for those who records many of their lectures on zoom but haven't locally saved their recordings already, such as online professors.

<!-- ———————————————————————————————— I: DocsToSheet ———————————————————————————————— -->

## I: DocsToSheet (Retreiving zoom links from google docs)

> This step allows you to retrieve all zoom links from google doc links, outputting the links to a google sheet for you to copy and paste into a .txt file. **If you already have the zoom links you wish to parse, you may skip this step.**

1.  Go to [Google App Scripts](https://script.google.com/home), and log in
2.  Create a new project on the top left
3.  In "Code.gs" (the script you'll already be on), paste the code found in the **"(Google Apps Script Code) DocsToSheet.txt"** file. It'll be located in the same ZoomScraping folder
4.  On Line 3 of the variable **"sheetName"**, you may change its name to whichever you may like to call it.

        (Ex.) const sheetName = "Docs to Zoom Links";

#### Now that the script is ready, we need to give the script the links needed to parse. It'll be using a .txt file and will be uploaded uploaded to your google drive temporarily

> **Before continuing, ensure all google docs wanting to be parsed can be publicably viewed!**

5.  Create a .txt file and paste all of your google docs you wish for the script to parse. The .txt may look like this, with each link having its own line.

        https://docs.google.com/document/d/(1)/edit?usp=sharing
        https://docs.google.com/document/d/(2)/edit?usp=sharing
        https://docs.google.com/document/d/(3)/edit?usp=sharing
        https://docs.google.com/document/d/(4)/edit?usp=sharing

6.  Upload the .txt to your google drive
7.  Once done, change the sharability to public and copy the link
8.  Returning back to the script, on line 2, change the initialization of publicDriveLink with the copied link.

#### Not all zoom recordings will have the same domain name and thus, it is important to find all domain names that needs to be retreived.

9.  Check your google docs and find a few hyperlinks that redirects to a zoom recording. Take note of all the different domain names that leads to a zoom recording.
    > No need to worry if you don't find all unique domain names. All links that were not included will also be included in the sheets and can be searched through if needed.
10. When you believe you found all the domain names that redirects to a zoom recording, return back to the script.
11. On Line 126, replace the value of the include function to the domain name you found. If there are more than one, add '||' and add another "link.include('domain name')".

        (Ex.) 	return link.includes('zoom1.com');
        		return link.includes('zoom1.com') || link.includes('zoom2.com');

### From this point, you may save the code (ctrl+s) and press run. You may be prompted to give the script permission to access your google sheets and google drive.

> Should the script throw errors, ensure all google docs and the .txt file are publically accessible.

12. When finished, the console will output a link to the newly created google sheet. In this, the first two column will contain the links of all found zoom links and from which doc it was located.
13. If you wish to double check and ensure you didn't miss any other zoom links, on the right side of the two columns will also have links that did not include the domain name. You can search through and double check if are any links that may also be a zoom link.

> If you do find any excluded zoom link, feel free to add it back to the first two column, or add its domain name to the script (step 11) and rerun the program again with a different sheet name (step 4).

14. If satisfied, copy all document title and zoom links together. An example is shown below of how it should look like
    <img src = "images/Example of Google Sheets Copy&Paste.png">

> If you wish to download all files into one document, rename everything below "Document Title" to a same name.

1.  Back in the ZoomScraping folder, in subfolder "ZoomDownloader", replace the entire text found in "zoom_links.txt" with the copied text from the google sheets. The .txt already has an example of how the formating should look like. If done correctly, the order should remain the same.
2.  From this point, we can move on part II of the program and download all zoom recordings.

#### A note on zoom_links.txt formatting

`zoom_links.txt` is tab-separated, and each line is auto-detected by how many tab-separated columns it has — you can mix both formats in the same file if you need to.

- **2 columns** — `Hyperlink Title<TAB>Zoom Link`. All files download into a single flat `BASE_OUTPUT_PATH` folder.
- **3 columns** — `Document Title<TAB>Hyperlink Title<TAB>Zoom Link`. A subfolder named after the Document Title is created inside `BASE_OUTPUT_PATH`.

        Course Overview	https://zoom.us/rec/share/...
        CSCI-10A-Video-Links-F25	Course Overview	https://zoom.us/rec/share/...

Either way, each downloaded file is renamed to `Hyperlink Title (SPECIAL) (original filename).ext` — e.g. `Course Overview (Video) (GMT20250819-175548_Recording_as_1920x1080).mp4`. `SPECIAL` is `Video` for the 1920x1080 stream, `Camera` for the 640x360 stream, or omitted for anything else (audio, transcript); the original Zoom filename is kept in parentheses for reference.

Any header row (e.g. a first line like `Document Title  Hyperlink Title  Zoom Link`) is skipped automatically, since its link column won't be an actual URL.

<!-- ———————————————————————————————— II: ZoomDownloader ———————————————————————————————— -->

## II: ZoomDownloader

> From this point, we'll start downloading all files from zoom recordings

1.  Install [latest Python version](https://www.python.org/downloads/windows/)
2.  After running the installation file, ensure to checkmark "Add python.exe to PATH" before installing
3.  Open Windows Terminal
4.  Run this command

        pip install selenium webdriver-manager requests

> The program automates a Chromium-based browser via Selenium — no Selenium-specific browser install is required beyond having one of the two available. Which one it uses is controlled by the "BROWSER" variable near the top of "zoom_downloader.py":
>
> - `BROWSER = 'edge'` (default) — uses Microsoft Edge, which comes pre-installed on Windows, so there's nothing else to set up.
> - `BROWSER = 'chrome'` — uses Google Chrome or Chromium. This is the better option on Linux, where Chromium is usually just a package-manager install away (e.g. `apt install chromium` / `dnf install chromium`), while Edge is not.

5.  Change the designation to the PATH of the ZoomDownloader folder. As such, an example would be

        cd "C:\Users\Name\Downloads\ZoomScraping\ZoomDownloader"

6.  (Optional) By default, files download into a "Results" folder created right next to "zoom_downloader.py". If you'd rather use a different location, change the "BASE_OUTPUT_PATH" variable near the top of "zoom_downloader.py" to the path you like, such as

        BASE_OUTPUT_PATH = r'C:\Users\Name\Downloads\Results'

7.  (Optional) You can modify which files should be excluded when downloading. In the "REMOVE_EXTENSIONS" variable near the top of "zoom_downloader.py", you can initiize it with any file extensions you wish to be excluded. There are comments that'll show examples if needed.

8.  When ready to parse all zoom links, run this command

        python zoom_downloader.py

9.  From this point, the program should work as intended and may take a while before finishing downloading files. You should be able to find the outputted results in the "Results" folder next to "zoom_downloader.py" (or the PATH you set on step 6).

> Console will output all errors related to downloading a file and will also show any links that had trouble doing so.

Every run also writes diagnostics to a "Debug" folder next to "zoom_downloader.py":
- **Debug/Snapshot** — a screenshot of the page at the moment a link is skipped or fails, named "Failure at (date/time) for (hyperlink title).png". Useful for cases where the failure reason isn't obvious from the console alone (e.g. the link turned out not to be a recording share page at all).
- **Debug/Logs** — a full copy of everything printed to the console for that run, one file per run named by its start time.
- **Debug/Finished Links.txt** — every link that's successfully downloaded, or been confirmed deleted, across every run. If "SKIP_FINISHED_LINKS" (near the top of "zoom_downloader.py") is left at its default of `True`, links already in this file are skipped on the next run instead of redone — handy for resuming after a crash or interruption without redoing completed work. Links that were skipped/failed aren't recorded, so they're always retried. Set it to `False` to always do a full run regardless of what's in the file (new completions still get recorded either way).
